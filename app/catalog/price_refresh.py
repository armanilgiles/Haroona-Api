from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models import AwinProductFeedRaw, AwinProductNormalized, Product, ProductPriceSnapshot
from app.utils.affiliate import is_affiliate


IN_STOCK_VALUES = {"in_stock", "in stock", "instock", "available", "true", "1"}
OUT_OF_STOCK_VALUES = {"out_of_stock", "out of stock", "sold_out", "sold out", "unavailable", "false", "0"}


@dataclass(frozen=True)
class ProductRefreshResult:
    checked: int = 0
    updated: int = 0
    unchanged: int = 0
    missing_normalized: int = 0
    deactivated: int = 0
    reactivated: int = 0
    snapshots_created: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "missing_normalized": self.missing_normalized,
            "deactivated": self.deactivated,
            "reactivated": self.reactivated,
            "snapshots_created": self.snapshots_created,
            "failed": self.failed,
        }


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _normalize_availability(value: Any) -> str:
    cleaned = (_clean_text(value) or "unknown").lower()
    return cleaned.replace("-", "_").replace(" ", "_")


def _is_in_stock(value: Any) -> bool:
    cleaned = (_clean_text(value) or "").lower()
    normalized = cleaned.replace("-", "_").replace(" ", "_")
    return cleaned in IN_STOCK_VALUES or normalized in IN_STOCK_VALUES


def _parse_price(raw_price: str | None) -> tuple[Decimal | None, str | None]:
    raw_price = _clean_text(raw_price)
    if not raw_price:
        return None, None

    match = re.match(r"^\s*([0-9]+(?:\.[0-9]{1,2})?)\s+([A-Z]{3})\s*$", raw_price)
    if not match:
        return None, None

    amount_str, currency = match.groups()

    try:
        return Decimal(amount_str), currency
    except InvalidOperation:
        return None, None


def _prices_differ(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None and right is None:
        return False
    if left is None or right is None:
        return True
    return Decimal(left) != Decimal(right)


def _find_normalized_row(db: Session, product: Product) -> AwinProductNormalized | None:
    if product.normalized_row_id:
        row = (
            db.query(AwinProductNormalized)
            .filter(AwinProductNormalized.id == product.normalized_row_id)
            .first()
        )
        if row:
            return row

    return (
        db.query(AwinProductNormalized)
        .filter(AwinProductNormalized.source == product.source)
        .filter(AwinProductNormalized.external_product_id == product.external_id)
        .first()
    )


def _regular_price_from_row(db: Session, row: AwinProductNormalized) -> Decimal | None:
    raw = db.query(AwinProductFeedRaw).filter(AwinProductFeedRaw.id == row.raw_id).first()
    if raw:
        amount, _currency = _parse_price(raw.price_raw)
        if amount is not None:
            return amount

    return row.price_amount


def refresh_products_from_normalized(
    db: Session,
    *,
    source: str | None = None,
    limit: int | None = None,
    deactivate_out_of_stock: bool = True,
) -> dict[str, int]:
    """Refresh promoted Product rows from normalized affiliate/feed rows.

    This does not scrape merchant pages. It expects the latest feed rows to already be
    imported and normalized. For Awin, that means running import_awin_csv and
    normalize_awin_raw before this refresh.
    """

    counts = {
        "checked": 0,
        "updated": 0,
        "unchanged": 0,
        "missing_normalized": 0,
        "deactivated": 0,
        "reactivated": 0,
        "snapshots_created": 0,
        "failed": 0,
    }

    query = db.query(Product).filter(Product.normalized_row_id.isnot(None)).order_by(Product.id.asc())

    if source:
        query = query.filter(Product.source == source)

    if limit is not None:
        query = query.limit(limit)

    products = query.all()
    now = datetime.now(timezone.utc)

    for product in products:
        counts["checked"] += 1

        try:
            row = _find_normalized_row(db, product)

            if not row:
                product.last_price_checked_at = now
                product.price_check_status = "missing_normalized"
                product.price_check_error = "No normalized feed row found for this product."
                counts["missing_normalized"] += 1
                continue

            old_price = product.price
            old_regular_price = product.regular_price
            old_availability = product.availability_status
            was_active = product.is_active

            new_price = row.price_amount if row.price_amount is not None else product.price
            new_regular_price = _regular_price_from_row(db, row)
            new_currency = row.currency or product.currency
            new_availability = _normalize_availability(row.availability)

            product.price = new_price
            product.regular_price = new_regular_price
            product.currency = new_currency
            product.availability_status = new_availability

            if row.affiliate_url:
                product.affiliate_url = row.affiliate_url
                product.is_affiliate = is_affiliate(row.affiliate_url)

            if row.merchant_url:
                product.merchant_url = row.merchant_url

            if row.image_url:
                product.product_image_url = row.image_url

            product.last_seen_at = now
            product.last_price_checked_at = now
            product.price_check_status = "ok"
            product.price_check_error = None
            product.normalized_row_id = row.id

            in_stock = _is_in_stock(row.availability)
            if deactivate_out_of_stock and row.availability and not in_stock:
                product.is_active = False
                product.deactivated_at = now
                product.deactivation_reason = f"price-refresh availability={new_availability}"
            elif in_stock:
                product.is_active = True
                product.deactivated_at = None
                product.deactivation_reason = None

            changed_price = _prices_differ(old_price, product.price)
            changed_regular_price = _prices_differ(old_regular_price, product.regular_price)
            changed_availability = old_availability != product.availability_status
            changed_active = was_active != product.is_active

            if changed_price or changed_regular_price or changed_availability:
                db.add(
                    ProductPriceSnapshot(
                        product_id=product.id,
                        source=product.source,
                        external_id=product.external_id,
                        old_price=old_price,
                        new_price=product.price,
                        old_regular_price=old_regular_price,
                        new_regular_price=product.regular_price,
                        old_availability_status=old_availability,
                        new_availability_status=product.availability_status,
                    )
                )
                counts["snapshots_created"] += 1

            if changed_active and not product.is_active:
                counts["deactivated"] += 1
            elif changed_active and product.is_active:
                counts["reactivated"] += 1

            if changed_price or changed_regular_price or changed_availability or changed_active:
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1

        except Exception as exc:
            counts["failed"] += 1
            product.last_price_checked_at = now
            product.price_check_status = "failed"
            product.price_check_error = str(exc)[:1000]

    return counts

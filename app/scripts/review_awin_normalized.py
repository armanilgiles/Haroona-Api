from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import AwinProductNormalized, CatalogBrandControl
from app.utils.normalize import normalize_brand


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split()).strip()
    return value or None


def get_allowed_brand_control(
    db,
    source: str,
    brand_name: str | None,
) -> CatalogBrandControl | None:
    if not brand_name:
        return None

    brand_key, _ = normalize_brand(brand_name)

    return (
        db.query(CatalogBrandControl)
        .filter(CatalogBrandControl.source == source)
        .filter(CatalogBrandControl.brand_key == brand_key)
        .filter(CatalogBrandControl.is_allowed.is_(True))
        .first()
    )


def decide_review_status(
    *,
    title: str | None,
    availability_lc: str,
    price_amount,
    currency: str | None,
    affiliate_url: str | None,
    merchant_url: str | None,
    image_url: str | None,
    brand_name: str | None,
    normalized_category: str | None,
    brand_control: CatalogBrandControl | None,
) -> tuple[bool, bool, str, str | None]:
    reject_reasons: list[str] = []
    pending_reasons: list[str] = []

    if not clean_text(title):
        reject_reasons.append("missing title")

    if availability_lc != "in_stock":
        reject_reasons.append("not in stock")

    if price_amount is None or not currency:
        reject_reasons.append("unparseable price")

    if not (affiliate_url or merchant_url):
        reject_reasons.append("missing affiliate url")

    if not image_url:
        reject_reasons.append("missing image")

    if not brand_name:
        reject_reasons.append("missing brand")

    if not normalized_category:
        pending_reasons.append("unknown category")

    if brand_name and not brand_control:
        pending_reasons.append("brand not allowlisted")

    is_usable = len(reject_reasons) == 0

    if reject_reasons:
        notes = "; ".join(reject_reasons + pending_reasons) or None
        return is_usable, False, "rejected", notes

    if pending_reasons:
        notes = "; ".join(pending_reasons) or None
        return is_usable, True, "pending", notes

    return True, False, "approved", None


def review_awin_normalized(limit: int | None = None) -> dict:
    db = SessionLocal()

    counts = {
        "approved": 0,
        "pending": 0,
        "rejected": 0,
        "skipped_manual": 0,
        "updated": 0,
    }

    try:
        query = db.query(AwinProductNormalized).order_by(AwinProductNormalized.id.asc())

        if limit is not None:
            query = query.limit(limit)

        rows = query.all()

        for row in rows:
            # Preserve manual reject/suppress decisions
            if row.review_status in {"rejected", "suppressed"} and row.reviewed_by not in {None, "", "auto-policy-v1"}:
                counts["skipped_manual"] += 1
                continue

            brand_control = get_allowed_brand_control(
                db=db,
                source=row.source,
                brand_name=row.brand_name,
            )

            availability_lc = (row.availability or "").strip().lower()

            is_usable, needs_review, review_status, review_notes = decide_review_status(
                title=row.title,
                availability_lc=availability_lc,
                price_amount=row.price_amount,
                currency=row.currency,
                affiliate_url=row.affiliate_url,
                merchant_url=row.merchant_url,
                image_url=row.image_url,
                brand_name=row.brand_name,
                normalized_category=row.normalized_category,
                brand_control=brand_control,
            )

            row.is_usable = is_usable
            row.needs_review = needs_review
            row.review_status = review_status
            row.review_notes = review_notes
            row.reviewed_by = "auto-policy-v1"
            row.reviewed_at = datetime.now(timezone.utc)
            row.rejection_reason = review_notes if review_status == "rejected" else None

            counts[review_status] += 1
            counts["updated"] += 1

        db.commit()
        return {"status": "ok", **counts}
    finally:
        db.close()


if __name__ == "__main__":
    limit = None

    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python -m app.scripts.review_awin_normalized [limit]")

    print(review_awin_normalized(limit=limit))
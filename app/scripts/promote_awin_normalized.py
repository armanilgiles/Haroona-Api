from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.models import (
    AwinProductNormalized,
    CatalogBrandControl,
    Country,
    Brand,
    Product,
)
from app.database import SessionLocal
from app.data.brand_map import BRAND_MAP
from app.utils.normalize import normalize_brand


COUNTRY_NAMES = {
    "US": "United States",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "BR": "Brazil",
    "ES": "Spain",
    "SE": "Sweden",
    "DK": "Denmark",
    "NL": "Netherlands",
}

def get_brand_control(db, source: str, brand_key: str) -> CatalogBrandControl | None:
    return (
        db.query(CatalogBrandControl)
        .filter(CatalogBrandControl.source == source)
        .filter(CatalogBrandControl.brand_key == brand_key)
        .filter(CatalogBrandControl.is_allowed.is_(True))
        .first()
    )
def get_or_create_country(db, code: str) -> Country:
    country = db.query(Country).filter(Country.code == code).first()
    if country:
        return country

    country = Country(
        code=code,
        name=COUNTRY_NAMES.get(code, code),
    )
    db.add(country)
    db.flush()
    return country


def get_or_create_brand(db, name: str, country_id: int) -> Brand:
    brand = (
        db.query(Brand)
        .filter(Brand.name == name)
        .filter(Brand.country_id == country_id)
        .first()
    )
    if brand:
        return brand

    brand = Brand(
        name=name,
        country_id=country_id,
        logo_url=None,
    )
    db.add(brand)
    db.flush()
    return brand


def upsert_product(db, row: AwinProductNormalized, brand_id: int) -> tuple[Product, str]:
    product = (
        db.query(Product)
        .filter(Product.external_id == row.external_product_id)
        .filter(Product.source == row.source)
        .first()
    )

    affiliate_url = row.affiliate_url or row.merchant_url
    if not affiliate_url:
        raise ValueError(f"row {row.id} missing affiliate/merchant URL")

    now = datetime.now(timezone.utc)

    if product:
        product.advertiser_id = row.advertiser_id
        product.name = row.title or product.name
        product.price = row.price_amount if row.price_amount is not None else product.price
        product.currency = row.currency or product.currency or "USD"
        product.affiliate_url = affiliate_url
        product.product_image_url = row.image_url or product.product_image_url
        product.product_image_alt = row.title or product.product_image_alt
        product.brand_id = brand_id
        product.category = row.normalized_category or product.category
        product.is_active = True
        product.normalized_row_id = row.id
        product.last_seen_at = now
        product.deactivated_at = None
        product.deactivation_reason = None
        return product, "updated"

    product = Product(
        external_id=row.external_product_id,
        source=row.source,
        advertiser_id=row.advertiser_id,
        name=row.title or "Untitled",
        price=row.price_amount,
        currency=row.currency or "USD",
        affiliate_url=affiliate_url,
        product_image_url=row.image_url,
        product_image_alt=row.title,
        brand_id=brand_id,
        city_id=None,
        category=row.normalized_category,
        style=None,
        vibe=None,
        is_best_seller=False,
        is_active=True,
        normalized_row_id=row.id,
        last_seen_at=now,
    )
    db.add(product)
    db.flush()
    return product, "created"


def promote_awin_normalized(limit: int | None = None) -> dict:
    db = SessionLocal()

    counts = {
        "created": 0,
        "updated": 0,
        "skipped_missing_brand": 0,
        "skipped_unmapped_brand": 0,
        "skipped_missing_country": 0,
        "skipped_missing_url": 0,
        "failed": 0,
    }

    try:
        query = (
            db.query(AwinProductNormalized)
            .filter(AwinProductNormalized.is_usable.is_(True))
            .filter(AwinProductNormalized.review_status == "approved")
            .order_by(AwinProductNormalized.id.asc())
        )

        if limit is not None:
            query = query.limit(limit)

        rows = query.all()

        for row in rows:
            try:
                brand_label = (row.brand_name or row.advertiser_name or "").strip()
                if not brand_label:
                    counts["skipped_missing_brand"] += 1
                    continue

                brand_key, confidence = normalize_brand(brand_label)
                brand_control = get_brand_control(db, row.source, brand_key)
                if not brand_control:
                    counts["skipped_unmapped_brand"] += 1
                    continue

                country_code = brand_control.origin_country_code
                if not country_code:
                    counts["skipped_missing_country"] += 1
                    continue

                if not (row.affiliate_url or row.merchant_url):
                    counts["skipped_missing_url"] += 1
                    continue

                country = get_or_create_country(db, country_code)
                brand = get_or_create_brand(db, brand_control.display_name, country.id)
                product, result = upsert_product(db, row, brand.id)

                row.promoted_at = datetime.now(timezone.utc)
                row.promoted_product_id = product.id

                db.commit()
                counts[result] += 1

            except Exception as exc:
                db.rollback()
                counts["failed"] += 1
                print(f"FAILED row_id={row.id} external_product_id={row.external_product_id}: {exc}")

        return {"status": "ok", **counts}

    finally:
        db.close()


if __name__ == "__main__":
    limit = None

    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python -m app.scripts.promote_awin_normalized [limit]")

    result = promote_awin_normalized(limit=limit)
    print(result)
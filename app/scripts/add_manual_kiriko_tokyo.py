from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    AwinProductFeedRaw,
    AwinProductNormalized,
    Brand,
    City,
    Country,
    Product,
)

SOURCE = "manual"
SOURCE_FILE = "manual-kiriko-tokyo"
ADVERTISER_ID = "kiriko-made"
BRAND_NAME = "Kiriko Made"
BRAND_LOGO_URL = None  # add a clean logo URL later if you get one

PRODUCTS = [
    {
        "external_id": "kiriko-original-v-neck-tunic-sunflower-chijimi",
        "sku": "KTOK01",
        "name": "Kiriko x ToK, V-Neck Tunic, Sunflower Chijimi",
        "price": Decimal("98.00"),
        "regular_price": Decimal("98.00"),
        "affiliate_url": "https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi",
        "merchant_url": "https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi",
        "image_url": "https://kirikomade.com/cdn/shop/files/DYL_8718_720x.png?v=1748454979",
        "category": "tops",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "availability": "out_of_stock",
        "is_active": True,  # change to False if you do NOT want sold-out products visible
    },
]


def get_or_create_country(db) -> Country:
    country = db.query(Country).filter(Country.code == "JP").first()
    if country:
        if country.name != "Japan":
            country.name = "Japan"
        return country

    country = Country(code="JP", name="Japan")
    db.add(country)
    db.flush()
    return country


def get_or_create_city(db, country_id: int) -> City:
    city = db.query(City).filter(City.slug == "tokyo").first()
    if city:
        city.name = "Tokyo"
        city.country_id = country_id
        city.latitude = Decimal("35.676400")
        city.longitude = Decimal("139.650000")
        if not city.marker_color:
            city.marker_color = "#E76F51"
        return city

    city = City(
        slug="tokyo",
        name="Tokyo",
        country_id=country_id,
        latitude=Decimal("35.676400"),
        longitude=Decimal("139.650000"),
        marker_color="#E76F51",
        image_url=None,
        followers=0,
    )
    db.add(city)
    db.flush()
    return city


def get_or_create_brand(db, country_id: int) -> Brand:
    brand = (
        db.query(Brand)
        .filter(Brand.name == BRAND_NAME)
        .filter(Brand.country_id == country_id)
        .first()
    )

    if brand:
        if BRAND_LOGO_URL:
            brand.logo_url = BRAND_LOGO_URL
        db.flush()
        return brand

    brand = Brand(
        name=BRAND_NAME,
        country_id=country_id,
        logo_url=BRAND_LOGO_URL,
    )
    db.add(brand)
    db.flush()
    return brand


def upsert_raw_row(db, item: dict) -> AwinProductFeedRaw:
    raw = (
        db.query(AwinProductFeedRaw)
        .filter(AwinProductFeedRaw.source_file == SOURCE_FILE)
        .filter(AwinProductFeedRaw.external_product_id == item["external_id"])
        .first()
    )

    payload = {
        "source": SOURCE,
        "merchant_url": item["merchant_url"],
        "affiliate_url": item["affiliate_url"],
        "regular_price": str(item["regular_price"]),
        "sale_price": str(item["price"]),
        "city_slug": "tokyo",
        "manually_curated": True,
        "availability": item["availability"],
    }

    if not raw:
        raw = AwinProductFeedRaw(
            source_file=SOURCE_FILE,
            external_product_id=item["external_id"],
            raw_payload=json.dumps(payload),
        )
        db.add(raw)

    raw.advertiser_id = ADVERTISER_ID
    raw.advertiser_name = BRAND_NAME
    raw.title = item["name"]
    raw.description = None
    raw.brand = BRAND_NAME
    raw.google_product_category = item["category"]
    raw.product_type = item["category"]
    raw.availability = item["availability"]
    raw.condition = "new"
    raw.price_raw = f'{item["regular_price"]} USD'
    raw.sale_price_raw = f'{item["price"]} USD'
    raw.link = item["merchant_url"]
    raw.aw_deep_link = item["affiliate_url"]
    raw.image_link = item["image_url"]
    raw.additional_image_link = None
    raw.raw_payload = json.dumps(payload)

    db.flush()
    return raw


def upsert_normalized_row(db, raw: AwinProductFeedRaw, item: dict) -> AwinProductNormalized:
    row = (
        db.query(AwinProductNormalized)
        .filter(AwinProductNormalized.source == SOURCE)
        .filter(AwinProductNormalized.external_product_id == item["external_id"])
        .first()
    )

    now = datetime.now(timezone.utc)

    if not row:
        row = AwinProductNormalized(
            raw_id=raw.id,
            source=SOURCE,
            external_product_id=item["external_id"],
        )
        db.add(row)

    row.raw_id = raw.id
    row.advertiser_id = ADVERTISER_ID
    row.advertiser_name = BRAND_NAME
    row.title = item["name"]
    row.description = None
    row.brand_name = BRAND_NAME
    row.price_amount = item["price"]
    row.currency = "USD"
    row.affiliate_url = item["affiliate_url"]
    row.merchant_url = item["merchant_url"]
    row.image_url = item["image_url"]
    row.availability = item["availability"]
    row.google_product_category = item["category"]
    row.product_type = item["category"]
    row.normalized_category = item["category"]
    row.is_usable = True
    row.needs_review = False
    row.review_status = "approved"
    row.reviewed_at = now
    row.reviewed_by = "manual-script"
    row.rejection_reason = None
    row.review_notes = "Manually curated Kiriko Made Tokyo product."
    row.haroona_style = item["style"]

    db.flush()
    return row


def upsert_product(db, item: dict, brand_id: int, city_id: int, normalized_row_id: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.source == SOURCE)
        .filter(Product.external_id == item["external_id"])
        .first()
    )

    now = datetime.now(timezone.utc)

    if not product:
        product = Product(
            source=SOURCE,
            external_id=item["external_id"],
            currency="USD",
            affiliate_url=item["affiliate_url"],
            brand_id=brand_id,
        )
        db.add(product)

    product.advertiser_id = ADVERTISER_ID
    product.name = item["name"]
    product.price = item["price"]
    product.currency = "USD"
    product.affiliate_url = item["affiliate_url"]
    product.product_image_url = item["image_url"]
    product.product_image_alt = item["name"]
    product.brand_id = brand_id
    product.city_id = city_id
    product.category = item["category"]
    product.style = item["style"]
    product.vibe = item["vibe"]
    product.is_best_seller = item["is_best_seller"]
    product.is_active = item["is_active"]
    product.normalized_row_id = normalized_row_id
    product.last_seen_at = now
    product.deactivated_at = None
    product.deactivation_reason = None

    db.flush()
    return product


def main() -> None:
    db = SessionLocal()
    created_or_updated = []

    try:
        country = get_or_create_country(db)
        city = get_or_create_city(db, country.id)
        brand = get_or_create_brand(db, country.id)

        for item in PRODUCTS:
            raw = upsert_raw_row(db, item)
            normalized = upsert_normalized_row(db, raw, item)
            product = upsert_product(
                db,
                item,
                brand_id=brand.id,
                city_id=city.id,
                normalized_row_id=normalized.id,
            )
            normalized.promoted_at = datetime.now(timezone.utc)
            normalized.promoted_product_id = product.id
            created_or_updated.append(product.name)

        db.commit()
        print(f"Added/updated {len(created_or_updated)} Tokyo Kiriko products:")
        for name in created_or_updated:
            print(f"- {name}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

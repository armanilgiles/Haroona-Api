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

SOURCE = "cj"
SOURCE_FILE = "manual-cj-amiclubwear-la"
ADVERTISER_ID = "11168474"
BRAND_NAME = "AMiClubWear"
BRAND_LOGO_URL = "https://amiclubwear.com/cdn/shop/files/amiclubwear_logo.jpg?v=1730305339"

PRODUCTS = [
    {
        "external_id": "wh2cla-btp2978x-r-id-wh2000543",
        "sku": "wh2000543",
        "name": "Plus Size Ribbed Long Cardigan & Leggings Set",
        "price": Decimal("62.50"),
        "regular_price": Decimal("125.00"),
        "affiliate_url": "https://www.anrdoezrs.net/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fwh2cla-btp2978x-r-id-wh2000543",
        "merchant_url": "https://amiclubwear.com/products/wh2cla-btp2978x-r-id-wh2000543",
        "image_url": "https://amiclubwear.com/cdn/shop/files/WH2000543_1800x1800.jpg?v=1737752309",
        "category": "bottoms",
        "style": "LA curve casual",
        "vibe": "soft-glam lounge",
        "is_best_seller": False,
    },
    {
        "external_id": "wh2cla-bd5504-id-wh200249558",
        "sku": "wh200249558",
        "name": "Ribbed Halter Neck Backless Bodycon Dress",
        "price": Decimal("24.75"),
        "regular_price": Decimal("42.00"),
        "affiliate_url": "https://www.tkqlhce.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fwh2cla-bd5504-id-wh200249558",
        "merchant_url": "https://amiclubwear.com/products/wh2cla-bd5504-id-wh200249558",
        "image_url": "https://amiclubwear.com/cdn/shop/files/WH200249558_1800x1800.jpg?v=1759467514",
        "category": "dress",
        "style": "LA bodycon",
        "vibe": "night-out",
        "is_best_seller": True,
    },
    {
        "external_id": "iri2-6-iset131sets-id-59401b",
        "sku": "59401b",
        "name": "Crop Tank Top & Cardigan Sweater Set",
        "price": Decimal("23.00"),
        "regular_price": Decimal("46.00"),
        "affiliate_url": "https://www.jdoqocy.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Firi2-6-iset131sets-id-59401b",
        "merchant_url": "https://amiclubwear.com/products/iri2-6-iset131sets-id-59401b",
        "image_url": "https://amiclubwear.com/cdn/shop/files/CC59401B_1800x1800.jpg?v=1744835214",
        "category": "tops",
        "style": "LA casual layered",
        "vibe": "soft city casual",
        "is_best_seller": True,
    },
    {
        "external_id": "mable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2",
        "sku": "100100103502572",
        "name": "MABLE 3 Pieces Sweater Set with Crop Cami, Mini Skirt, Cardigan",
        "price": Decimal("94.99"),
        "regular_price": Decimal("189.99"),
        "affiliate_url": "https://www.jdoqocy.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fmable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2",
        "merchant_url": "https://amiclubwear.com/products/mable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2",
        "image_url": "https://amiclubwear.com/cdn/shop/files/3bc4bc71-1e36-4761-9d17-a8509c41552b-Max_1800x1800.jpg?v=1726603821",
        "category": "skirt",
        "style": "LA boutique set",
        "vibe": "polished soft glam",
        "is_best_seller": True,
    },
]


def get_or_create_country(db) -> Country:
    country = db.query(Country).filter(Country.code == "US").first()
    if country:
        if country.name != "United States":
            country.name = "United States"
        return country

    country = Country(code="US", name="United States")
    db.add(country)
    db.flush()
    return country


def get_or_create_city(db, country_id: int) -> City:
    city = db.query(City).filter(City.slug == "los-angeles").first()
    if city:
        city.name = "Los Angeles"
        city.country_id = country_id
        city.latitude = Decimal("34.052235")
        city.longitude = Decimal("-118.243683")
        if not city.marker_color:
            city.marker_color = "#F4A261"
        return city

    city = City(
        slug="los-angeles",
        name="Los Angeles",
        country_id=country_id,
        latitude=Decimal("34.052235"),
        longitude=Decimal("-118.243683"),
        marker_color="#F4A261",
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
        "city_slug": "los-angeles",
        "manually_curated": True,
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
    raw.availability = "in_stock"
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
    row.availability = "in_stock"
    row.google_product_category = item["category"]
    row.product_type = item["category"]
    row.normalized_category = item["category"]
    row.is_usable = True
    row.needs_review = False
    row.review_status = "approved"
    row.reviewed_at = now
    row.reviewed_by = "manual-script"
    row.rejection_reason = None
    row.review_notes = "Manually curated CJ/AMIClubWear Los Angeles product."
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
    product.is_active = True
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
        print(f"Added/updated {len(created_or_updated)} Los Angeles AMiClubWear products:")
        for name in created_or_updated:
            print(f"- {name}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
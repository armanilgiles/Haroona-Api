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
SOURCE_FILE = "manual-cj-rainbow-nyc"
ADVERTISER_ID = "12398826"
BRAND_NAME = "Rainbow Shops"
BRAND_LOGO_URL = "https://cdn.brandfetch.io/idhZZX-Z_I/w/209/h/75/theme/dark/logo.png?c=1dxbfHSJFAPEGdCLU4o5B"

PRODUCTS = [
    {
        "external_id": "rainbow-dress-1",
        "sku": "rainbow-dress-1",
        "name": "Black Ponte Halter Mini Skater Dress",
        "price": Decimal("19.99"),
        "regular_price": Decimal("29.99"),
        "affiliate_url": "https://www.tkqlhce.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/black-ponte-halter-mini-skater-dress-1094077667002",
        "merchant_url": "https://www.rainbowshops.com/products/black-ponte-halter-mini-skater-dress-1094077667002",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/1094077667002001_001.jpg?v=1776811499&width=1300",
        "category": "dress",
        "style": "NYC night",
        "vibe": "edgy nightlife",
        "is_best_seller": True,
    },
    {
        "external_id": "rainbow-jeans-1",
        "sku": "rainbow-jeans-1",
        "name": "Light Wash High Waisted Straight Leg Jeans",
        "price": Decimal("24.99"),
        "regular_price": Decimal("34.99"),
        "affiliate_url": "https://www.anrdoezrs.net/click-101726370-12398826?url=https://www.rainbowshops.com/products/light-wash-high-waisted-whiskered-straight-leg-jeans-3074071618630",
        "merchant_url": "https://www.rainbowshops.com/products/light-wash-high-waisted-whiskered-straight-leg-jeans-3074071618630",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/3074071618630402_001.jpg?v=1776769580&width=1300",
        "category": "bottom",
        "style": "NYC casual",
        "vibe": "city everyday",
        "is_best_seller": False,
    },
    {
        "external_id": "rainbow-skirt-1",
        "sku": "rainbow-skirt-1",
        "name": "Wine Faux Leather Mini Pencil Skirt",
        "price": Decimal("19.99"),
        "regular_price": Decimal("29.99"),
        "affiliate_url": "https://www.tkqlhce.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/wine-faux-leather-mini-pencil-skirt-3406068512527",
        "merchant_url": "https://www.rainbowshops.com/products/wine-faux-leather-mini-pencil-skirt-3406068512527",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/3406068512527061_001_bd23e0c1-d1ab-4cd5-976d-78ec65215946.jpg?v=1776783054&width=1300",
    "video_url": "https://www.rainbowshops.com/cdn/shop/videos/c/vp/d75316222d1146d8b56b7577ee9e763a/d75316222d1146d8b56b7577ee9e763a.HD-1080p-7.2Mbps-64589935.mp4?v=0",
       
        "category": "bottom",
        "style": "NYC night",
        "vibe": "edgy",
        "is_best_seller": True,
    },
    {
        "external_id": "rainbow-top-1",
        "sku": "rainbow-top-1",
        "name": "Black Ruched Side Buckle Strap Halter Top",
        "price": Decimal("14.99"),
        "regular_price": Decimal("19.99"),
        "affiliate_url": "https://www.jdoqocy.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/black-ruched-side-buckle-strap-halter-top-1402069393331",
        "merchant_url": "https://www.rainbowshops.com/products/black-ruched-side-buckle-strap-halter-top-1402069393331",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/1402069393331001_001_31581fbe-3376-420f-a5d2-604bfca37548.jpg?v=1776806219&width=1300",
        "category": "top",
        "style": "NYC street",
        "vibe": "confident",
        "is_best_seller": False,
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
    city = db.query(City).filter(City.slug == "new-york").first()
    if city:
        city.name = "New York"
        city.country_id = country_id
        city.latitude = Decimal("40.7128")
        city.longitude = Decimal("-74.0060")
        if not city.marker_color:
            city.marker_color = "#1D3557"
        return city

    city = City(
        slug="new-york",
        name="New York",
        country_id=country_id,
        latitude=Decimal("40.7128"),
        longitude=Decimal("-74.0060"),
        marker_color="#1D3557",
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
        "city_slug": "new-york",
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
    row.brand_name = BRAND_NAME
    row.price_amount = item["price"]
    row.currency = "USD"
    row.affiliate_url = item["affiliate_url"]
    row.merchant_url = item["merchant_url"]
    row.image_url = item["image_url"]
    row.video_url = item.get("video_url")
    row.availability = "in_stock"
    row.normalized_category = item["category"]
    row.is_usable = True
    row.needs_review = False
    row.review_status = "approved"
    row.reviewed_at = now
    row.reviewed_by = "manual-script"
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
    product.video_url = "https://www.rainbowshops.com/cdn/shop/videos/c/vp/d75316222d1146d8b56b7577ee9e763a/d75316222d1146d8b56b7577ee9e763a.HD-1080p-7.2Mbps-64589935.mp4?v=0"    
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

    db.flush()
    return product


def main() -> None:
    db = SessionLocal()

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

        db.commit()
        print(f"✅ Added/updated {len(PRODUCTS)} NYC Rainbow products")

    except Exception as e:
        db.rollback()
        print("❌ Error:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
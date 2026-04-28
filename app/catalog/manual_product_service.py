from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.catalog.manual_seed_types import ManualProductSeed
from app.database import SessionLocal
from app.models import (
    AwinProductFeedRaw,
    AwinProductNormalized,
    Brand,
    City,
    Country,
    Product,
)
from app.utils.affiliate import is_affiliate


REQUIRED_PRODUCT_KEYS = (
    "external_id",
    "name",
    "price",
    "affiliate_url",
    "merchant_url",
    "image_url",
    "category",
    "style",
    "vibe",
    "is_best_seller",
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))


def _validate_item(item: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_PRODUCT_KEYS if key not in item]

    if missing:
        external_id = item.get("external_id", "unknown")
        raise ValueError(f"Manual product {external_id} is missing keys: {missing}")


def get_or_create_country(db: Session, seed: ManualProductSeed) -> Country:
    country = db.query(Country).filter(Country.code == seed.country_code).first()

    if country:
        country.name = seed.country_name
        db.flush()
        return country

    country = Country(code=seed.country_code, name=seed.country_name)
    db.add(country)
    db.flush()
    return country


def get_or_create_city(
    db: Session,
    seed: ManualProductSeed,
    country_id: int,
) -> City:
    city = db.query(City).filter(City.slug == seed.city_slug).first()

    if city:
        city.name = seed.city_name
        city.country_id = country_id
        city.latitude = seed.latitude
        city.longitude = seed.longitude

        if seed.marker_color and not city.marker_color:
            city.marker_color = seed.marker_color

        db.flush()
        return city

    city = City(
        slug=seed.city_slug,
        name=seed.city_name,
        country_id=country_id,
        latitude=seed.latitude,
        longitude=seed.longitude,
        marker_color=seed.marker_color,
        image_url=None,
        followers=0,
    )

    db.add(city)
    db.flush()
    return city


def get_or_create_brand(
    db: Session,
    seed: ManualProductSeed,
    country_id: int,
) -> Brand:
    brand = (
        db.query(Brand)
        .filter(Brand.name == seed.brand_name)
        .filter(Brand.country_id == country_id)
        .first()
    )

    if brand:
        if seed.brand_logo_url:
            brand.logo_url = seed.brand_logo_url

        db.flush()
        return brand

    brand = Brand(
        name=seed.brand_name,
        country_id=country_id,
        logo_url=seed.brand_logo_url,
    )

    db.add(brand)
    db.flush()
    return brand


def upsert_raw_row(
    db: Session,
    seed: ManualProductSeed,
    item: Mapping[str, Any],
) -> AwinProductFeedRaw:
    _validate_item(item)

    external_id = str(item["external_id"])
    price = _to_decimal(item.get("price"))
    regular_price = _to_decimal(item.get("regular_price", price))
    availability = str(item.get("availability") or seed.default_availability)

    raw = (
        db.query(AwinProductFeedRaw)
        .filter(AwinProductFeedRaw.source_file == seed.source_file)
        .filter(AwinProductFeedRaw.external_product_id == external_id)
        .first()
    )

    payload = {
        "source": seed.source,
        "merchant_url": item["merchant_url"],
        "affiliate_url": item["affiliate_url"],
        "regular_price": regular_price,
        "sale_price": price,
        "city_slug": seed.city_slug,
        "manually_curated": True,
        "availability": availability,
        "video_url": item.get("video_url"),
    }

    if not raw:
        raw = AwinProductFeedRaw(
            source_file=seed.source_file,
            external_product_id=external_id,
            raw_payload=json.dumps(payload, default=str),
        )
        db.add(raw)

    raw.advertiser_id = seed.advertiser_id
    raw.advertiser_name = seed.brand_name
    raw.title = item["name"]
    raw.description = item.get("description")
    raw.brand = seed.brand_name
    raw.google_product_category = item.get("google_product_category") or item["category"]
    raw.product_type = item.get("product_type") or item["category"]
    raw.availability = availability
    raw.condition = "new"
    raw.price_raw = f"{regular_price} {seed.currency}" if regular_price is not None else None
    raw.sale_price_raw = f"{price} {seed.currency}" if price is not None else None
    raw.link = item["merchant_url"]
    raw.aw_deep_link = item["affiliate_url"]
    raw.image_link = item["image_url"]
    raw.additional_image_link = item.get("additional_image_url")
    raw.raw_payload = json.dumps(payload, default=str)

    db.flush()
    return raw


def upsert_normalized_row(
    db: Session,
    seed: ManualProductSeed,
    raw: AwinProductFeedRaw,
    item: Mapping[str, Any],
) -> AwinProductNormalized:
    _validate_item(item)

    external_id = str(item["external_id"])
    now = datetime.now(timezone.utc)
    availability = str(item.get("availability") or seed.default_availability)

    row = (
        db.query(AwinProductNormalized)
        .filter(AwinProductNormalized.source == seed.source)
        .filter(AwinProductNormalized.external_product_id == external_id)
        .first()
    )

    if not row:
        row = AwinProductNormalized(
            raw_id=raw.id,
            source=seed.source,
            external_product_id=external_id,
        )
        db.add(row)

    row.raw_id = raw.id
    row.advertiser_id = seed.advertiser_id
    row.advertiser_name = seed.brand_name
    row.title = item["name"]
    row.description = item.get("description")
    row.brand_name = seed.brand_name
    row.price_amount = _to_decimal(item.get("price"))
    row.currency = seed.currency
    row.affiliate_url = item["affiliate_url"]
    row.merchant_url = item["merchant_url"]
    row.image_url = item["image_url"]
    row.availability = availability
    row.google_product_category = item.get("google_product_category") or item["category"]
    row.product_type = item.get("product_type") or item["category"]
    row.normalized_category = item["category"]
    row.is_usable = True
    row.needs_review = False
    row.review_status = "approved"
    row.reviewed_at = now
    row.reviewed_by = "manual-script"
    row.rejection_reason = None
    row.review_notes = seed.review_notes
    row.haroona_style = item["style"]

    db.flush()
    return row


def upsert_product(
    db: Session,
    seed: ManualProductSeed,
    item: Mapping[str, Any],
    brand_id: int,
    city_id: int,
    normalized_row_id: int,
) -> Product:
    _validate_item(item)

    external_id = str(item["external_id"])
    now = datetime.now(timezone.utc)

    product = (
        db.query(Product)
        .filter(Product.source == seed.source)
        .filter(Product.external_id == external_id)
        .first()
    )

    if not product:
        product = Product(
            source=seed.source,
            external_id=external_id,
            currency=seed.currency,
            affiliate_url=item["affiliate_url"],
            brand_id=brand_id,
        )
        db.add(product)

    product.advertiser_id = seed.advertiser_id
    product.name = item["name"]
    product.price = _to_decimal(item.get("price"))
    product.currency = seed.currency
    product.affiliate_url = item.get("affiliate_url") or None
    product.merchant_url = item.get("merchant_url") or None
    product.is_affiliate = is_affiliate(item.get("affiliate_url") or "")
    product.product_image_url = item["image_url"]
    product.product_image_alt = item.get("image_alt") or item["name"]
    product.video_url = item.get("video_url")
    product.brand_id = brand_id
    product.city_id = city_id
    product.category = item["category"]
    product.style = item["style"]
    product.vibe = item["vibe"]
    product.is_best_seller = bool(item.get("is_best_seller", False))
    product.is_active = bool(item.get("is_active", True))
    product.normalized_row_id = normalized_row_id
    product.last_seen_at = now
    product.deactivated_at = None
    product.deactivation_reason = None

    db.flush()
    return product


def seed_manual_products(seed: ManualProductSeed) -> list[str]:
    db = SessionLocal()
    created_or_updated: list[str] = []

    try:
        country = get_or_create_country(db, seed)
        city = get_or_create_city(db, seed, country.id)
        brand = get_or_create_brand(db, seed, country.id)

        for item in seed.products:
            raw = upsert_raw_row(db, seed, item)
            normalized = upsert_normalized_row(db, seed, raw, item)

            product = upsert_product(
                db,
                seed,
                item,
                brand_id=brand.id,
                city_id=city.id,
                normalized_row_id=normalized.id,
            )

            normalized.promoted_at = datetime.now(timezone.utc)
            normalized.promoted_product_id = product.id
            created_or_updated.append(product.name)

        db.commit()
        return created_or_updated

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

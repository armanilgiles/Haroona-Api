from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.data.mock_products_ui import MOCK_UI_PRODUCTS
from app.models import Brand, Country, Product


router = APIRouter(prefix="/dev", tags=["dev"])


def _get_or_create_country(db: Session, code: str, name: str) -> Country:
    existing = db.query(Country).filter(Country.code == code).first()
    if existing:
        if name and existing.name != name:
            existing.name = name
        return existing
    c = Country(code=code, name=name)
    db.add(c)
    db.flush()
    return c


def _get_or_create_brand(db: Session, name: str, country_id: int, logo_url: str | None) -> Brand:
    existing = (
        db.query(Brand)
        .filter(Brand.name == name)
        .filter(Brand.country_id == country_id)
        .first()
    )
    if existing:
        if logo_url and existing.logo_url != logo_url:
            existing.logo_url = logo_url
        return existing
    b = Brand(name=name, country_id=country_id, logo_url=logo_url)
    db.add(b)
    db.flush()
    return b


def _upsert_product(db: Session, p: dict, brand_id: int):
    external_id = p["productId"]
    source = "mock"

    existing = (
        db.query(Product)
        .filter(Product.external_id == external_id)
        .filter(Product.source == source)
        .first()
    )

    if existing:
        # Update fields if they changed
        existing.name = p.get("productName") or existing.name
        existing.currency = p.get("currency") or existing.currency
        existing.affiliate_url = p.get("affiliateUrl") or existing.affiliate_url
        existing.advertiser_id = p.get("advertiserId") or existing.advertiser_id
        existing.product_image_url = (p.get("productImage") or {}).get("url") or existing.product_image_url
        existing.product_image_alt = (p.get("productImage") or {}).get("alt") or existing.product_image_alt
        price_str = p.get("price")
        if price_str:
            try:
                existing.price = Decimal(price_str)
            except Exception:
                pass
        existing.brand_id = brand_id
        return existing

    price_val = None
    price_str = p.get("price")
    if price_str:
        try:
            price_val = Decimal(price_str)
        except Exception:
            price_val = None

    prod = Product(
        external_id=external_id,
        source=source,
        advertiser_id=p.get("advertiserId"),
        name=p.get("productName") or "",
        price=price_val,
        currency=p.get("currency") or "USD",
        affiliate_url=p.get("affiliateUrl") or "",
        product_image_url=(p.get("productImage") or {}).get("url"),
        product_image_alt=(p.get("productImage") or {}).get("alt"),
        brand_id=brand_id,
    )
    db.add(prod)
    return prod


@router.post("/seed-ui")
def seed_ui(db: Session = Depends(get_db)):
    """Seed UI-aligned sample data for local dev.

    This makes /products return the exact shape your UI expects.
    """

    created = 0
    updated = 0

    for item in MOCK_UI_PRODUCTS:
        country = _get_or_create_country(
            db,
            code=item.get("countryCode") or "US",
            name=item.get("countryName") or "United States",
        )

        brand = _get_or_create_brand(
            db,
            name=item.get("brandName") or "",
            country_id=country.id,
            logo_url=(item.get("logoImage") or {}).get("url"),
        )

        before = (
            db.query(Product)
            .filter(Product.external_id == item["productId"])
            .filter(Product.source == "mock")
            .first()
        )

        _upsert_product(db, item, brand_id=brand.id)

        if before:
            updated += 1
        else:
            created += 1

    db.commit()

    return {
        "status": "ok",
        "products_created": created,
        "products_updated": updated,
        "note": "Now call GET /products and you should see productImage + logoImage.",
    }

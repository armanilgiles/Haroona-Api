from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Brand, Country, Product
from app.schemas import BrandMini, ImageAssetOut, ProductCardOut
from app.utils.brand_registry import lookup_logo_url
from app.utils.normalize import normalize_brand

router = APIRouter(prefix="/products", tags=["products"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _price_to_str(value) -> str | None:
    if value is None:
        return None
    try:
        return format(value, "f")
    except Exception:
        return str(value)


def _to_product_card(p: Product) -> ProductCardOut:
    brand_name = p.brand.name if p.brand else None
    advertiser_id = p.advertiser_id
    if not advertiser_id and brand_name:
        normalized_key, _ = normalize_brand(brand_name)
        advertiser_id = normalized_key.replace(" ", "")

    external = p.external_id or str(p.id)
    product_id = external if "-" in external else f"{p.source}-{external}"

    product_image_url = getattr(p, "product_image_url", None)
    product_image_alt = getattr(p, "product_image_alt", None) or p.name

    # Source of truth: Brand.logo_url (DB)
    logo_url = getattr(p.brand, "logo_url", None) if p.brand else None
    if not logo_url:
        logo_url = lookup_logo_url(brand_name=brand_name, advertiser_id=advertiser_id)
    logo_alt = f"{brand_name} logo" if brand_name else "Merchant logo"

    return ProductCardOut(
        productId=product_id,
        productName=p.name,
        advertiserId=advertiser_id,
        brandName=brand_name,
        price=_price_to_str(p.price),
        currency=p.currency,
        affiliateUrl=p.affiliate_url,
        productImage=(
            ImageAssetOut(url=product_image_url, alt=product_image_alt)
            if product_image_url
            else None
        ),
        logoImage=(ImageAssetOut(url=logo_url, alt=logo_alt) if logo_url else None),

        # Back-compat
        id=p.id,
        name=p.name,
        brand=(
            BrandMini(id=p.brand.id, name=brand_name, logo_url=logo_url)
            if p.brand and brand_name
            else None
        ),
        imageUrl=product_image_url,
        imageAlt=product_image_alt,
    )


@router.get("", response_model=List[ProductCardOut])
def get_products(
    country: str | None = Query(
        None,
        description="ISO 3166-1 alpha-2 country code (e.g. BR). If provided, results are prioritized for that country.",
        min_length=2,
        max_length=2,
    ),
    brand_id: int | None = Query(None, description="Optional brand id filter."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Join Brand -> Country so we can prioritize by country.
    query = db.query(Product).join(Brand).join(Country)

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    # Prioritize matches first (not strict filtering).
    if country:
        c = country.upper()
        priority = case((Country.code == c, 0), else_=1)
        query = query.order_by(priority, Product.id.desc())
    else:
        query = query.order_by(Product.id.desc())

    products = query.offset(offset).limit(limit).all()
    return [_to_product_card(p) for p in products]
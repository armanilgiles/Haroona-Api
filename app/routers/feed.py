from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, distinct, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, Brand, City, Country
from app.schemas import FeedFiltersOut, FeedProductOut, FeedResponse, ImageAssetOut

router = APIRouter(prefix="/feed", tags=["feed"])


def _price_to_str(value) -> str | None:
    if value is None:
        return None
    try:
        return format(value, "f")
    except Exception:
        return str(value)


@router.get("/products", response_model=FeedResponse)
def get_feed_products(
    city: str | None = Query(None, description="City slug, e.g. tokyo"),
    mode: str = Query("prioritize", pattern="^(prioritize|lock)$"),
    category: str | None = Query(None),
    style: str | None = Query(None),
    vibe: str | None = Query(None),
    q: str | None = Query(None),
    brand_id: int | None = Query(None),
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Product)
        .join(Brand)
        .outerjoin(City)
        .outerjoin(Country, City.country_id == Country.id)
        .filter(Product.is_active.is_(True))
    )

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    if category:
        query = query.filter(Product.category == category)

    if style:
        query = query.filter(Product.style == style)

    if vibe:
        query = query.filter(Product.vibe == vibe)

    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(like),
                Brand.name.ilike(like),
                Product.category.ilike(like),
                Product.style.ilike(like),
                Product.vibe.ilike(like),
            )
        )

    if city and mode == "lock":
        query = query.filter(City.slug == city)

    count_query = query

    if city and mode == "prioritize":
        priority = case((City.slug == city, 0), else_=1)
        query = query.order_by(priority, Product.is_best_seller.desc(), Product.id.desc())
    else:
        query = query.order_by(Product.is_best_seller.desc(), Product.id.desc())

    total = count_query.with_entities(func.count(Product.id)).scalar() or 0
    products = query.offset(offset).limit(limit).all()

    items: list[FeedProductOut] = []

    for p in products:
        brand_name = p.brand.name if p.brand else None
        city_obj = p.city
        country_obj = city_obj.country if city_obj else None

        logo_url = p.brand.logo_url if p.brand else None
        logo_alt = f"{brand_name} logo" if brand_name else "Merchant logo"

        external = p.external_id or str(p.id)
        product_id = external if "-" in external else f"{p.source}-{external}"

        items.append(
            FeedProductOut(
                productId=product_id,
                productName=p.name,
                advertiserId=p.advertiser_id,
                brandName=brand_name,
                price=_price_to_str(p.price),
                currency=p.currency,
                affiliateUrl=p.affiliate_url,
                productImage=(
                    ImageAssetOut(url=p.product_image_url, alt=p.product_image_alt or p.name)
                    if p.product_image_url
                    else None
                ),
                logoImage=(ImageAssetOut(url=logo_url, alt=logo_alt) if logo_url else None),
                citySlug=city_obj.slug if city_obj else None,
                cityName=city_obj.name if city_obj else None,
                countryCode=country_obj.code if country_obj else None,
                countryName=country_obj.name if country_obj else None,
                category=p.category,
                style=p.style,
                vibe=p.vibe,
                isBestSeller=p.is_best_seller,
            )
        )

    return FeedResponse(items=items, total=total, selectedCity=city, mode=mode)


@router.get("/filters", response_model=FeedFiltersOut)
def get_feed_filters(db: Session = Depends(get_db)):
    categories = [
        row[0]
        for row in db.query(distinct(Product.category))
        .filter(Product.category.isnot(None))
        .order_by(Product.category.asc())
        .all()
    ]
    styles = [
        row[0]
        for row in db.query(distinct(Product.style))
        .filter(Product.style.isnot(None))
        .order_by(Product.style.asc())
        .all()
    ]
    vibes = [
        row[0]
        for row in db.query(distinct(Product.vibe))
        .filter(Product.vibe.isnot(None))
        .order_by(Product.vibe.asc())
        .all()
    ]

    return FeedFiltersOut(categories=categories, styles=styles, vibes=vibes)

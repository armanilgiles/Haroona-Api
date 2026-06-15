from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, distinct, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, Brand, City, Country
from app.schemas import FeedCategoryGroupOut, FeedFiltersOut, FeedProductOut, FeedResponse, ImageAssetOut


router = APIRouter(prefix="/feed", tags=["feed"])


CATEGORY_GROUPS = [
    {"key": "all", "label": "All", "values": []},
    {"key": "dresses", "label": "Dresses", "values": ["dress"]},
    {"key": "tops", "label": "Tops", "values": ["tops"]},
    {"key": "bottoms", "label": "Bottoms", "values": ["bottoms", "pants", "skirt", "shorts"]},
    {"key": "sets", "label": "Sets", "values": ["set"]},
    {"key": "shoes", "label": "Shoes", "values": ["shoe", "shoes", "sneaker", "sneakers", "footwear"]},
]


def _price_to_str(value) -> str | None:
    if value is None:
        return None

    try:
        return format(value, "f")
    except Exception:
        return str(value)


def _apply_curated_catalog_gate(query):
    return (
        query
        .filter(Product.is_active.is_(True))
        .filter(Product.normalized_row_id.isnot(None))
    )



def _normalize_filter_value(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.strip().lower()
    return normalized or None


def _normalize_filter_values(values: list[str] | None) -> list[str]:
    normalized_values: list[str] = []

    for raw_value in values or []:
        for part in raw_value.split(","):
            normalized = _normalize_filter_value(part)

            if normalized and normalized not in normalized_values:
                normalized_values.append(normalized)

    return normalized_values

def _normalize_city_slug(value: str | None) -> str | None:
    if not value:
        return None

    return value.strip().lower().replace(" ", "-")


def _normalize_city_slugs(values: list[str] | None) -> list[str]:
    slugs: list[str] = []

    for raw_value in values or []:
        for part in raw_value.split(","):
            slug = _normalize_city_slug(part)

            if slug and slug not in slugs:
                slugs.append(slug)

    return slugs


@router.get("/products", response_model=FeedResponse)
def get_feed_products(
    city: str | None = Query(None, description="Single city slug, e.g. tokyo"),
    cities: list[str] | None = Query(
        None,
        description="Multiple city slugs, e.g. ?cities=tokyo,seoul or ?cities=tokyo&cities=seoul",
    ),
    city_slugs: list[str] | None = Query(
        None,
        description="Alias for cities. Supports ?city_slugs=tokyo,seoul or repeated city_slugs params.",
    ),
    mode: str = Query("lock", pattern="^(prioritize|lock)$"),
    category: str | None = Query(None),
    categories: list[str] | None = Query(
        None,
        description="Multiple product categories, e.g. ?categories=bottoms,pants,skirt or repeated categories params.",
    ),
    style: str | None = Query(None),
    vibe: str | None = Query(None),
    city_connection_type: str | None = Query(
        None,
        description="City connection type: local_boutique, city_based_brand, city_inspired_pick",
    ),
    q: str | None = Query(None),
    brand_id: int | None = Query(None),
    per_city_limit: int | None = Query(
        None,
        ge=1,
        le=100,
        description=(
            "Optional cap per city for all-city discovery pages. "
            "The cap is applied with the same product ordering as the feed."
        ),
    ),
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Product)
        .join(Brand)
        .outerjoin(City)
        .outerjoin(Country, City.country_id == Country.id)
    )

    query = _apply_curated_catalog_gate(query)

    selected_city_slugs = _normalize_city_slugs(cities)

    for city_slug in _normalize_city_slugs(city_slugs):
        if city_slug not in selected_city_slugs:
            selected_city_slugs.append(city_slug)

    selected_city_slug = _normalize_city_slug(city)

    if selected_city_slug and selected_city_slug not in selected_city_slugs:
        selected_city_slugs.insert(0, selected_city_slug)

    if selected_city_slugs:
        query = query.filter(City.slug.in_(selected_city_slugs))

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    selected_categories = _normalize_filter_values(categories)
    selected_category = _normalize_filter_value(category)

    if selected_category and selected_category not in selected_categories:
        selected_categories.insert(0, selected_category)

    if selected_categories:
        query = query.filter(func.lower(Product.category).in_(selected_categories))

    if style:
        query = query.filter(Product.style == style)

    if vibe:
        query = query.filter(Product.vibe == vibe)

    if city_connection_type:
        query = query.filter(Product.city_connection_type == city_connection_type)

    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(like),
                Brand.name.ilike(like),
                Product.category.ilike(like),
                Product.style.ilike(like),
                Product.vibe.ilike(like),
                Product.city_connection_type.ilike(like),
                Product.city_connection_location.ilike(like),
                Product.city_connection_note.ilike(like),
            )
        )

    shoes_last = case(
        (func.lower(Product.category).in_(["shoe", "shoes", "sneaker", "sneakers", "footwear"]), 1),
        else_=0,
    )
    product_ordering = (
        shoes_last.asc(),
        Product.is_best_seller.desc(),
        Product.id.desc(),
    )

    if per_city_limit and not selected_city_slugs:
        ranked_products = query.with_entities(
            Product.id.label("product_id"),
            func.row_number()
            .over(
                partition_by=Product.city_id,
                order_by=product_ordering,
            )
            .label("city_rank"),
        ).subquery()

        query = (
            db.query(Product)
            .join(ranked_products, Product.id == ranked_products.c.product_id)
            .join(Brand)
            .outerjoin(City)
            .outerjoin(Country, City.country_id == Country.id)
            .filter(ranked_products.c.city_rank <= per_city_limit)
        )

    count_query = query

    query = query.order_by(*product_ordering)

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
                merchantUrl=p.merchant_url,
                isAffiliate=p.is_affiliate,
                productImage=(
                    ImageAssetOut(
                        url=p.product_image_url,
                        alt=p.product_image_alt or p.name,
                    )
                    if p.product_image_url
                    else None
                ),
                videoUrl=p.video_url,
                logoImage=(
                    ImageAssetOut(url=logo_url, alt=logo_alt)
                    if logo_url
                    else None
                ),

                cityConnectionType=p.city_connection_type,
                cityConnectionLocation=p.city_connection_location,
                cityConnectionNote=p.city_connection_note,

                citySlug=city_obj.slug if city_obj else None,
                cityName=city_obj.name if city_obj else None,
                category=p.category,
                style=p.style,
                vibe=p.vibe,
                isBestSeller=p.is_best_seller,
            )
        )

    return FeedResponse(
        items=items,
        total=total,
        selectedCity=city,
        selectedCities=selected_city_slugs,
        selectedCategories=selected_categories,
        mode=mode,
        limit=limit,
        offset=offset,
        nextOffset=offset + len(items) if offset + len(items) < total else None,
        hasMore=offset + len(items) < total,
    )


@router.get("/filters", response_model=FeedFiltersOut)
def get_feed_filters(db: Session = Depends(get_db)):
    base = (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .filter(Product.normalized_row_id.isnot(None))
        .filter(Product.city_id.isnot(None))
    )

    categories = [
        row[0]
        for row in base.with_entities(distinct(Product.category))
        .filter(Product.category.isnot(None))
        .order_by(Product.category.asc())
        .all()
    ]

    styles = [
        row[0]
        for row in base.with_entities(distinct(Product.style))
        .filter(Product.style.isnot(None))
        .order_by(Product.style.asc())
        .all()
    ]

    vibes = [
        row[0]
        for row in base.with_entities(distinct(Product.vibe))
        .filter(Product.vibe.isnot(None))
        .order_by(Product.vibe.asc())
        .all()
    ]

    city_connection_types = [
        row[0]
        for row in base.with_entities(distinct(Product.city_connection_type))
        .filter(Product.city_connection_type.isnot(None))
        .order_by(Product.city_connection_type.asc())
        .all()
    ]

    category_count_rows = (
        base.with_entities(func.lower(Product.category), func.count(Product.id))
        .filter(Product.category.isnot(None))
        .group_by(func.lower(Product.category))
        .all()
    )
    category_counts = {category: count for category, count in category_count_rows if category}
    total_products = sum(category_counts.values())

    category_groups = []
    for group in CATEGORY_GROUPS:
        values = group["values"]
        count = total_products if not values else sum(category_counts.get(value, 0) for value in values)

        category_groups.append(
            FeedCategoryGroupOut(
                key=group["key"],
                label=group["label"],
                values=values,
                count=count,
                isAvailable=count > 0,
            )
        )

    return FeedFiltersOut(
        categories=categories,
        categoryGroups=category_groups,
        styles=styles,
        vibes=vibes,
        cityConnectionTypes=city_connection_types,
    )

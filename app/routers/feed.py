import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, distinct, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, Brand, City, Country
from app.schemas import FeedCategoryGroupOut, FeedFiltersOut, FeedProductOut, FeedResponse, ImageAssetOut


router = APIRouter(prefix="/feed", tags=["feed"])


CATEGORY_GROUPS = [
    {"key": "all", "label": "All", "values": []},
    {"key": "dresses", "label": "Dresses", "values": ["dress", "dresses", "gown", "gowns"]},
    {
        "key": "tops",
        "label": "Tops",
        "values": [
            "top",
            "tops",
            "shirt",
            "shirts",
            "blouse",
            "blouses",
            "tee",
            "tees",
            "t-shirt",
            "t-shirts",
            "vest",
            "vests",
            "camisole",
            "camisoles",
            "tank",
            "tanks",
        ],
    },
    {
        "key": "bottoms",
        "label": "Bottoms",
        "values": [
            "bottom",
            "bottoms",
            "pant",
            "pants",
            "trouser",
            "trousers",
            "jean",
            "jeans",
            "skirt",
            "skirts",
            "short",
            "shorts",
        ],
    },
    {"key": "sets", "label": "Sets", "values": ["set", "sets", "co-ord", "co-ords", "co ord", "co ords"]},
    {"key": "shoes", "label": "Shoes", "values": ["shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "heel", "heels", "sandal", "sandals", "footwear"]},
    {"key": "bags", "label": "Bags", "values": ["bag", "bags", "handbag", "handbags", "purse", "purses", "tote", "totes"]},
    {"key": "accessories", "label": "Accessories", "values": ["accessory", "accessories", "belt", "belts", "hat", "hats", "scarf", "scarves"]},
    {"key": "jewelry", "label": "Jewelry", "values": ["jewelry", "jewellery", "necklace", "necklaces", "earring", "earrings", "bracelet", "bracelets", "ring", "rings"]},
]


CATEGORY_ALIASES = {
    "dress": "dresses",
    "dresses": "dresses",
    "gown": "dresses",
    "gowns": "dresses",
    "top": "tops",
    "tops": "tops",
    "shirt": "tops",
    "shirts": "tops",
    "blouse": "tops",
    "blouses": "tops",
    "tee": "tops",
    "tees": "tops",
    "t-shirt": "tops",
    "t-shirts": "tops",
    "camisole": "tops",
    "camisoles": "tops",
    "tank": "tops",
    "tanks": "tops",
    "vest": "tops",
    "vests": "tops",
    "bottom": "bottoms",
    "bottoms": "bottoms",
    "pant": "bottoms",
    "pants": "bottoms",
    "trouser": "bottoms",
    "trousers": "bottoms",
    "jean": "bottoms",
    "jeans": "bottoms",
    "skirt": "bottoms",
    "skirts": "bottoms",
    "short": "bottoms",
    "shorts": "bottoms",
    "set": "sets",
    "sets": "sets",
    "co-ord": "sets",
    "co-ords": "sets",
    "co ord": "sets",
    "co ords": "sets",
    "shoe": "shoes",
    "shoes": "shoes",
    "sneaker": "shoes",
    "sneakers": "shoes",
    "boot": "shoes",
    "boots": "shoes",
    "heel": "shoes",
    "heels": "shoes",
    "sandal": "shoes",
    "sandals": "shoes",
    "footwear": "shoes",
    "bag": "bags",
    "bags": "bags",
    "handbag": "bags",
    "handbags": "bags",
    "purse": "bags",
    "purses": "bags",
    "tote": "bags",
    "totes": "bags",
    "jewelry": "jewelry",
    "jewellery": "jewelry",
    "necklace": "jewelry",
    "necklaces": "jewelry",
    "earring": "jewelry",
    "earrings": "jewelry",
    "bracelet": "jewelry",
    "bracelets": "jewelry",
    "ring": "jewelry",
    "rings": "jewelry",
    "accessory": "accessories",
    "accessories": "accessories",
    "belt": "accessories",
    "belts": "accessories",
    "hat": "accessories",
    "hats": "accessories",
    "scarf": "accessories",
    "scarves": "accessories",
}

CATEGORY_INFERENCE_RULES = [
    (["dress", "gown"], "dresses"),
    (["skirt", "trouser", "pant", "jean", "short"], "bottoms"),
    (["top", "blouse", "shirt", "vest", "tee", "t-shirt", "camisole", "tank"], "tops"),
    (["co-ord", "co-ords", "co ord", "co ords", "set"], "sets"),
    (["bag", "handbag", "purse", "tote"], "bags"),
    (["shoe", "sandal", "boot", "heel", "sneaker"], "shoes"),
    (["necklace", "earring", "bracelet", "ring", "jewellery", "jewelry"], "jewelry"),
]


def _slugify_category(value: str) -> str:
    slug = value.strip().lower().replace("&", "and")
    slug = "-".join(part for part in slug.replace("_", "-").split() if part)
    slug = "".join(char if char.isalnum() or char == "-" else "-" for char in slug)

    while "--" in slug:
        slug = slug.replace("--", "-")

    return slug.strip("-")



def _canonical_category(value: str | None) -> str | None:
    if not value:
        return None

    normalized = _slugify_category(value)
    if not normalized:
        return None

    return CATEGORY_ALIASES.get(normalized, normalized)


def _keyword_pattern(keyword: str) -> str:
    # Match whole-ish words across spaces/hyphens without matching things like
    # "topaz". Examples: "Sia Top", "t-shirt", "co ord".
    escaped = re.escape(keyword).replace(r"\ ", r"[\s-]+")
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"


def _text_has_keyword(text: str, keyword: str) -> bool:
    return re.search(_keyword_pattern(keyword), text.lower()) is not None


def _infer_category_from_title(title: str | None) -> str | None:
    haystack = title or ""
    if not haystack:
        return None

    for keywords, category in CATEGORY_INFERENCE_RULES:
        if any(_text_has_keyword(haystack, keyword) for keyword in keywords):
            return category

    return None


def _resolve_product_category(title: str | None, category: str | None) -> str | None:
    # Title wins over stale category values. This fixes already-published items
    # that were scanned with a collection hint like "dresses" even though the
    # product title is "Sia Top".
    inferred = _infer_category_from_title(title)
    if inferred:
        return inferred

    return _canonical_category(category)


def _category_title_filter_clauses(selected_categories: list[str]):
    selected = {_canonical_category(value) for value in selected_categories}
    selected.discard(None)

    clauses = []
    for keywords, category in CATEGORY_INFERENCE_RULES:
        if category not in selected:
            continue

        for keyword in keywords:
            clauses.append(Product.name.ilike(f"%{keyword}%"))

    return clauses


def _label_category(value: str) -> str:
    custom_labels = {
        "co-ords": "Sets",
        "co-ord": "Sets",
        "t-shirt": "T-Shirts",
        "t-shirts": "T-Shirts",
    }
    slug = _slugify_category(value)
    if slug in custom_labels:
        return custom_labels[slug]

    return " ".join(part.capitalize() for part in slug.split("-") if part) or value.title()


def _build_category_groups(category_counts: dict[str, int]) -> list[FeedCategoryGroupOut]:
    total_products = sum(category_counts.values())
    groups: list[FeedCategoryGroupOut] = [
        FeedCategoryGroupOut(
            key="all",
            label="All",
            values=[],
            count=total_products,
            isAvailable=total_products > 0,
        )
    ]

    claimed_values: set[str] = set()

    for group in CATEGORY_GROUPS:
        if group["key"] == "all":
            continue

        values = [_slugify_category(value) for value in group["values"]]
        count = sum(category_counts.get(value, 0) for value in values)

        if count <= 0:
            continue

        claimed_values.update(values)
        groups.append(
            FeedCategoryGroupOut(
                key=group["key"],
                label=group["label"],
                values=values,
                count=count,
                isAvailable=True,
            )
        )

    dynamic_categories = sorted(
        (category, count)
        for category, count in category_counts.items()
        if count > 0 and category not in claimed_values
    )

    for category, count in dynamic_categories:
        groups.append(
            FeedCategoryGroupOut(
                key=_slugify_category(category),
                label=_label_category(category),
                values=[category],
                count=count,
                isAvailable=True,
            )
        )

    return groups


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
        .filter(Product.city_id.isnot(None))
        .filter(or_(Product.normalized_row_id.isnot(None), Product.source == "shopify"))
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
        selected_category_aliases = {
            _canonical_category(value) for value in selected_categories
        }
        selected_category_aliases.discard(None)
        selected_category_values = list({
            *selected_categories,
            *[value for value in selected_category_aliases if value],
        })

        query = query.filter(
            or_(
                func.lower(Product.category).in_(selected_category_values),
                *_category_title_filter_clauses(selected_categories),
            )
        )

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
                        url=p.optimized_product_image_url or p.product_image_url,
                        alt=p.product_image_alt or p.name,
                        width=p.product_image_width,
                        height=p.product_image_height,
                    )
                    if (p.optimized_product_image_url or p.product_image_url)
                    else None
                ),
                originalProductImage=(
                    ImageAssetOut(
                        url=p.product_image_url,
                        alt=p.product_image_alt or p.name,
                    )
                    if p.optimized_product_image_url and p.product_image_url
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
                category=_resolve_product_category(p.name, p.category) or p.category,
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
        .filter(Product.city_id.isnot(None))
        .filter(or_(Product.normalized_row_id.isnot(None), Product.source == "shopify"))
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

    category_rows = base.with_entities(Product.name, Product.category).all()
    category_counts: dict[str, int] = {}
    for product_name, category in category_rows:
        normalized_category = _resolve_product_category(product_name, category)
        if not normalized_category:
            continue

        category_counts[normalized_category] = (
            category_counts.get(normalized_category, 0) + 1
        )

    category_groups = _build_category_groups(category_counts)

    return FeedFiltersOut(
        categories=categories,
        categoryGroups=category_groups,
        styles=styles,
        vibes=vibes,
        cityConnectionTypes=city_connection_types,
    )

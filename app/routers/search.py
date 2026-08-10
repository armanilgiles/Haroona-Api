from __future__ import annotations

import unicodedata

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import String, and_, case, func, literal, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Brand, City, Country, Product
from app.schemas import (
    SearchBrandOut,
    SearchCityOut,
    SearchFacetOut,
    SearchHasMoreOut,
    SearchProductOut,
    SearchResponse,
)


router = APIRouter(prefix="/search", tags=["search"])

MINIMUM_QUERY_LENGTH = 2
MAX_QUERY_TERMS = 8


def _normalize_query(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.split()).casefold()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_pattern(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _prefix_pattern(value: str) -> str:
    return f"{_escape_like(value)}%"


def _catalog_gate(query):
    return (
        query.filter(Product.is_active.is_(True))
        .filter(Product.city_id.isnot(None))
        .filter(or_(Product.normalized_row_id.isnot(None), Product.source == "shopify"))
    )


def _text_terms(query: str) -> list[str]:
    return query.split()[:MAX_QUERY_TERMS]


def _matches_all_terms(columns, terms: list[str]):
    return and_(
        *(
            or_(
                *(column.ilike(_contains_pattern(term), escape="\\") for column in columns)
            )
            for term in terms
        )
    )


def _text_rank(column, query: str):
    return case(
        (func.lower(column) == query, 0),
        (func.lower(column).like(_prefix_pattern(query), escape="\\"), 1),
        else_=2,
    )


def _take(rows: list, limit: int) -> tuple[list, bool]:
    return rows[:limit], len(rows) > limit


def _facet_label(value: str) -> str:
    cleaned = value.strip().replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in cleaned.split())


def _public_product_id(external_id: str | None, source: str, db_id: int) -> str:
    external = external_id or str(db_id)
    return external if "-" in external else f"{source}-{external}"


def _empty_response(query: str) -> SearchResponse:
    return SearchResponse(
        query=query,
        minimumQueryLength=MINIMUM_QUERY_LENGTH,
        hasMore=SearchHasMoreOut(),
    )


@router.get("", response_model=SearchResponse)
def search_catalog(
    response: Response,
    q: str = Query("", max_length=100),
    limit: int = Query(6, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Return small, grouped search suggestions from the public Haroona catalog."""

    normalized_query = _normalize_query(q)
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"

    if len(normalized_query) < MINIMUM_QUERY_LENGTH:
        return _empty_response(normalized_query)

    terms = _text_terms(normalized_query)
    fetch_limit = limit + 1

    city_rows = (
        db.query(
            City.id,
            City.slug,
            City.name,
            Country.code,
            Country.name,
        )
        .join(Country, City.country_id == Country.id)
        .filter(_matches_all_terms((City.name, City.slug), terms))
        .order_by(_text_rank(City.name, normalized_query), City.name.asc(), City.id.asc())
        .limit(fetch_limit)
        .all()
    )
    city_rows, cities_has_more = _take(city_rows, limit)

    curated_brand_product = (
        db.query(Product.id)
        .filter(Product.brand_id == Brand.id)
        .filter(Product.is_active.is_(True))
        .filter(Product.city_id.isnot(None))
        .filter(or_(Product.normalized_row_id.isnot(None), Product.source == "shopify"))
        .exists()
    )
    brand_rows = (
        db.query(Brand.id, Brand.name, Brand.logo_url)
        .filter(curated_brand_product)
        .filter(_matches_all_terms((Brand.name,), terms))
        .order_by(_text_rank(Brand.name, normalized_query), Brand.name.asc(), Brand.id.asc())
        .limit(fetch_limit)
        .all()
    )
    brand_rows, brands_has_more = _take(brand_rows, limit)

    category_query = _catalog_gate(db.query(Product.category)).filter(
        Product.category.isnot(None),
        _matches_all_terms((Product.category,), terms),
    )
    category_rows = (
        category_query.group_by(Product.category)
        .order_by(
            _text_rank(Product.category, normalized_query),
            Product.category.asc(),
        )
        .limit(fetch_limit)
        .all()
    )
    category_rows, categories_has_more = _take(category_rows, limit)

    style_query = _catalog_gate(
        db.query(
            Product.style.label("value"),
            literal("style", type_=String()).label("kind"),
        )
    ).filter(
        Product.style.isnot(None),
        _matches_all_terms((Product.style,), terms),
    )
    vibe_query = _catalog_gate(
        db.query(
            Product.vibe.label("value"),
            literal("vibe", type_=String()).label("kind"),
        )
    ).filter(
        Product.vibe.isnot(None),
        _matches_all_terms((Product.vibe,), terms),
    )
    style_values = style_query.union_all(vibe_query).subquery()
    style_rows = (
        db.query(style_values.c.value, func.min(style_values.c.kind).label("kind"))
        .group_by(style_values.c.value)
        .order_by(
            _text_rank(style_values.c.value, normalized_query),
            style_values.c.value.asc(),
        )
        .limit(fetch_limit)
        .all()
    )
    style_rows, styles_has_more = _take(style_rows, limit)

    product_columns = (
        Product.name,
        Brand.name,
        Product.category,
        Product.style,
        Product.vibe,
        City.name,
    )
    product_rank = case(
        (func.lower(Product.name) == normalized_query, 0),
        (func.lower(Brand.name) == normalized_query, 1),
        (func.lower(City.name) == normalized_query, 1),
        (func.lower(Product.name).like(_prefix_pattern(normalized_query), escape="\\"), 2),
        (func.lower(Brand.name).like(_prefix_pattern(normalized_query), escape="\\"), 3),
        else_=4,
    )
    product_query = (
        db.query(
            Product.id,
            Product.external_id,
            Product.source,
            Product.name,
            Brand.name,
            Product.category,
            Product.style,
            Product.vibe,
            City.slug,
            City.name,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(City, Product.city_id == City.id)
    )
    product_rows = (
        _catalog_gate(product_query)
        .filter(_matches_all_terms(product_columns, terms))
        .order_by(
            product_rank,
            Product.is_best_seller.desc(),
            Product.id.desc(),
        )
        .limit(fetch_limit)
        .all()
    )
    product_rows, products_has_more = _take(product_rows, limit)

    return SearchResponse(
        query=normalized_query,
        minimumQueryLength=MINIMUM_QUERY_LENGTH,
        cities=[
            SearchCityOut(
                id=row[0],
                slug=row[1],
                name=row[2],
                countryCode=row[3],
                countryName=row[4],
            )
            for row in city_rows
        ],
        categories=[
            SearchFacetOut(value=row[0], label=_facet_label(row[0]), kind="category")
            for row in category_rows
        ],
        brands=[
            SearchBrandOut(id=row[0], name=row[1], logoUrl=row[2])
            for row in brand_rows
        ],
        styles=[
            SearchFacetOut(value=row[0], label=_facet_label(row[0]), kind=row[1])
            for row in style_rows
        ],
        products=[
            SearchProductOut(
                productId=_public_product_id(row[1], row[2], row[0]),
                dbProductId=row[0],
                productName=row[3],
                brandName=row[4],
                category=row[5],
                style=row[6],
                vibe=row[7],
                citySlug=row[8],
                cityName=row[9],
            )
            for row in product_rows
        ],
        hasMore=SearchHasMoreOut(
            cities=cities_has_more,
            categories=categories_has_more,
            brands=brands_has_more,
            styles=styles_has_more,
            products=products_has_more,
        ),
    )

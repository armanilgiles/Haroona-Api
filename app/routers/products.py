import math
import re
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AwinProductFeedRaw,
    AwinProductNormalized,
    Brand,
    City,
    Country,
    Product,
    ProductCandidate,
)
from app.schemas import (
    BrandMini,
    ImageAssetOut,
    ProductCardOut,
    ProductCityAnalysisOut,
    ProductCityScoreComponentOut,
    ProductDetailOut,
)
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


def _public_product_id(product: Product) -> str:
    external = product.external_id or str(product.id)
    return external if "-" in external else f"{product.source}-{external}"


def _normalize_city_slug(value: str | None) -> str | None:
    if not value:
        return None

    return value.strip().lower().replace(" ", "-")


def _to_product_card(p: Product) -> ProductCardOut:
    brand_name = p.brand.name if p.brand else None
    advertiser_id = p.advertiser_id
    if not advertiser_id and brand_name:
        normalized_key, _ = normalize_brand(brand_name)
        advertiser_id = normalized_key.replace(" ", "")

    product_id = _public_product_id(p)

    original_product_image_url = getattr(p, "product_image_url", None)
    optimized_product_image_url = getattr(p, "optimized_product_image_url", None)
    product_image_url = optimized_product_image_url or original_product_image_url
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
        merchantUrl=p.merchant_url,
        isAffiliate=p.is_affiliate,
        productImage=(
            ImageAssetOut(
                url=product_image_url,
                alt=product_image_alt,
                width=getattr(p, "product_image_width", None),
                height=getattr(p, "product_image_height", None),
            )
            if product_image_url
            else None
        ),
        originalProductImage=(
            ImageAssetOut(url=original_product_image_url, alt=product_image_alt)
            if optimized_product_image_url and original_product_image_url
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


MATCH_LABELS = {
    "distinctive_primary_match": "Primary Match",
    "primary_match": "Primary Match",
    "strong_multi_city_fit": "Strong Multi-City Fit",
    "city_leaning": "City-Leaning",
    "broad_match": "Broad Match",
    "legacy_haroona_selection": "Haroona Selection",
    "legacy_city_fit": "City Fit",
}

CITY_SCORE_COMPONENT_LABELS = {
    "visual_aesthetic": "Visual",
    "climate_practicality": "Climate",
    "lifestyle_occasion": "Lifestyle",
    "distinctive_enhancement": "Distinctiveness",
}
CITY_SCORE_COMPONENT_ORDER = tuple(CITY_SCORE_COMPONENT_LABELS)
CITY_SCORE_REASON_KEYS = {
    "visual": "visual_aesthetic",
    "climate": "climate_practicality",
    "lifestyle": "lifestyle_occasion",
    "distinctive": "distinctive_enhancement",
    "distinctiveness": "distinctive_enhancement",
}
SCORE_FRACTION_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _component_reasons(analysis: dict[str, Any], key: str) -> list[str]:
    raw_reasons = analysis.get("component_reasons")
    if not isinstance(raw_reasons, dict):
        return []
    values = raw_reasons.get(key)
    if not isinstance(values, list):
        return []
    return _unique_text(values, limit=3)


def _city_score_components(
    item: dict[str, Any],
    analysis: dict[str, Any],
) -> list[ProductCityScoreComponentOut]:
    points = analysis.get("component_points")
    maximums = analysis.get("component_max_points")
    components: list[ProductCityScoreComponentOut] = []

    if isinstance(points, dict) and isinstance(maximums, dict):
        for key in CITY_SCORE_COMPONENT_ORDER:
            score = _finite_number(points.get(key))
            max_score = _finite_number(maximums.get(key))
            if score is None or max_score is None or max_score <= 0:
                continue
            components.append(
                ProductCityScoreComponentOut(
                    key=key,
                    label=CITY_SCORE_COMPONENT_LABELS[key],
                    score=score,
                    maxScore=max_score,
                    reasons=_component_reasons(analysis, key),
                )
            )
        if components:
            return components

    # Older candidate rows predate structured component persistence. Their
    # score reasons still contain the real weighted points emitted by the
    # scoring engine, so expose those values without recomputing a score.
    score_reasons = item.get("score_reasons")
    if not isinstance(score_reasons, list):
        return []
    parsed: dict[str, ProductCityScoreComponentOut] = {}
    for raw_reason in score_reasons:
        reason = _clean_text(raw_reason)
        if not reason:
            continue
        first_word = reason.split(maxsplit=1)[0].lower()
        key = CITY_SCORE_REASON_KEYS.get(first_word)
        fractions = SCORE_FRACTION_RE.findall(reason)
        if not key or not fractions:
            continue
        raw_score, raw_max_score = fractions[-1]
        score = _finite_number(raw_score)
        max_score = _finite_number(raw_max_score)
        if score is None or max_score is None or max_score <= 0:
            continue
        parsed[key] = ProductCityScoreComponentOut(
            key=key,
            label=CITY_SCORE_COMPONENT_LABELS[key],
            score=score,
            maxScore=max_score,
        )
    return [parsed[key] for key in CITY_SCORE_COMPONENT_ORDER if key in parsed]

DISCOVERY_LABELS = {
    "local_boutique": "Local Boutique",
    "city_based_brand": "City-Based Brand",
    "city_inspired_pick": "City-Inspired Pick",
}

UNAVAILABLE_STATUSES = {
    "archived",
    "discontinued",
    "inactive",
    "out_of_stock",
    "sold_out",
    "unavailable",
}


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _unique_text(values: list[Any], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


def _match_label(
    match_type: str | None,
    *,
    rank: int,
    score: int | None,
    primary_match_eligible: bool | None,
) -> str:
    normalized = _clean_text(match_type)
    if normalized:
        existing = MATCH_LABELS.get(normalized.lower())
        if existing:
            return existing
        return normalized.replace("_", " ").replace("-", " ").title()

    if rank == 1 and primary_match_eligible is not False:
        return "Primary Match"
    if score is not None and score >= 80:
        return "Strong Alternative"
    if score is not None and score >= 70:
        return "Good Match"
    return "Lower Match"


def _candidate_for_product(db: Session, product_id: int) -> ProductCandidate | None:
    return (
        db.query(ProductCandidate)
        .filter(ProductCandidate.promoted_product_id == product_id)
        .order_by(ProductCandidate.updated_at.desc(), ProductCandidate.id.desc())
        .first()
    )


def _normalized_product(
    db: Session,
    product: Product,
) -> tuple[AwinProductNormalized | None, AwinProductFeedRaw | None]:
    if not product.normalized_row_id:
        return None, None

    normalized = db.get(AwinProductNormalized, product.normalized_row_id)
    raw = db.get(AwinProductFeedRaw, normalized.raw_id) if normalized else None
    return normalized, raw


def _find_product(db: Session, identifier: str) -> Product | None:
    normalized_identifier = identifier.strip()
    if not normalized_identifier:
        return None

    base = db.query(Product)
    product = (
        base.filter(Product.external_id == normalized_identifier)
        .order_by(Product.id.desc())
        .first()
    )
    if product:
        return product

    product = (
        base.filter(
            (Product.source + "-" + Product.external_id) == normalized_identifier
        )
        .order_by(Product.id.desc())
        .first()
    )
    if product:
        return product

    if normalized_identifier.isdigit():
        return db.get(Product, int(normalized_identifier))
    return None


def _city_analysis(
    db: Session,
    product: Product,
    candidate: ProductCandidate | None,
) -> list[ProductCityAnalysisOut]:
    raw_candidates: list[dict[str, Any]] = []
    if candidate and isinstance(candidate.city_candidates, list):
        raw_candidates = [
            item for item in candidate.city_candidates if isinstance(item, dict)
        ]

    if not raw_candidates and candidate and isinstance(candidate.city_fit_scores, dict):
        raw_candidates = [
            {"city_slug": city_slug, "city_fit_score": score}
            for city_slug, score in candidate.city_fit_scores.items()
        ]

    if not raw_candidates and candidate and candidate.target_city_slug:
        raw_candidates = [
            {
                "city_slug": candidate.target_city_slug,
                "city_fit_score": candidate.city_fit_score,
                "confidence": candidate.scoring_confidence,
                "city_connection_note": candidate.city_connection_note,
            }
        ]

    if not raw_candidates and product.city:
        raw_candidates = [{"city_slug": product.city.slug}]

    city_slugs = _unique_text(
        [item.get("city_slug") for item in raw_candidates]
    )
    city_names = {
        city.slug: city.name
        for city in db.query(City).filter(City.slug.in_(city_slugs)).all()
    } if city_slugs else {}

    normalized_rows: list[dict[str, Any]] = []
    for item in raw_candidates:
        slug = _clean_text(item.get("city_slug"))
        if not slug:
            continue
        raw_score = item.get("city_fit_score")
        if raw_score is None:
            raw_score = item.get("score")
        try:
            score = int(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None

        raw_confidence = item.get("confidence")
        try:
            confidence = (
                int(raw_confidence) if raw_confidence is not None else None
            )
        except (TypeError, ValueError):
            confidence = None

        analysis = item.get("scoring_analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        explanation = _clean_text(analysis.get("comparative_reason"))
        explanation = explanation or _clean_text(item.get("city_connection_note"))
        if not explanation and product.city and product.city.slug == slug:
            explanation = _clean_text(product.city_connection_note)

        score_reasons = item.get("score_reasons")
        if not explanation and isinstance(score_reasons, list):
            explanation = next(
                (
                    reason
                    for reason in (_clean_text(value) for value in reversed(score_reasons))
                    if reason
                ),
                None,
            )

        normalized_rows.append(
            {
                "city_slug": slug,
                "city_name": city_names.get(slug, slug.replace("-", " ").title()),
                "score": score,
                "confidence": confidence,
                "match_type": _clean_text(item.get("match_type")),
                "primary_match_eligible": item.get("primary_match_eligible"),
                "explanation": explanation,
                "score_components": _city_score_components(item, analysis),
            }
        )

    normalized_rows.sort(
        key=lambda item: (
            -(item["score"] if item["score"] is not None else -1),
            item["city_name"],
        )
    )

    return [
        ProductCityAnalysisOut(
            citySlug=item["city_slug"],
            cityName=item["city_name"],
            score=item["score"],
            confidence=item["confidence"],
            matchLabel=_match_label(
                item["match_type"],
                rank=rank,
                score=item["score"],
                primary_match_eligible=item["primary_match_eligible"],
            ),
            matchType=item["match_type"],
            rank=rank,
            explanation=item["explanation"],
            scoreComponents=item["score_components"],
        )
        for rank, item in enumerate(normalized_rows, start=1)
    ]


def _to_product_detail(db: Session, product: Product) -> ProductDetailOut:
    candidate = _candidate_for_product(db, product.id)
    normalized, raw = _normalized_product(db, product)
    brand_name = product.brand.name if product.brand else None
    logo_url = product.brand.logo_url if product.brand else None
    if not logo_url:
        logo_url = lookup_logo_url(
            brand_name=brand_name,
            advertiser_id=product.advertiser_id,
        )

    main_image_url = product.optimized_product_image_url or product.product_image_url
    image_alt = product.product_image_alt or product.name
    additional_urls: list[str] = []
    if raw:
        additional_urls = _unique_text([raw.additional_image_link])
    additional_images = [
        ImageAssetOut(url=url, alt=f"{product.name} alternate view")
        for url in additional_urls
        if url != main_image_url
    ]

    description = _clean_text(candidate.description) if candidate else None
    description = description or (_clean_text(normalized.description) if normalized else None)
    description = description or (_clean_text(raw.description) if raw else None)

    selected_analysis = (
        candidate.scoring_analysis
        if candidate and isinstance(candidate.scoring_analysis, dict)
        else {}
    )
    detail_values: list[Any] = []
    if candidate and isinstance(candidate.manual_observed_garment_details, list):
        detail_values.extend(candidate.manual_observed_garment_details)
    observed_details = selected_analysis.get("observed_garment_details")
    if isinstance(observed_details, list):
        detail_values.extend(observed_details)
    details = _unique_text(detail_values, limit=12)

    tag_values: list[Any] = [product.style, product.vibe]
    recognized_concepts = selected_analysis.get("recognized_concepts")
    if isinstance(recognized_concepts, list):
        tag_values.extend(recognized_concepts)
    style_tags = _unique_text(tag_values, limit=8)

    city_analysis = _city_analysis(db, product, candidate)
    why_it_fits = _clean_text(product.city_connection_note)
    if not why_it_fits and city_analysis:
        why_it_fits = city_analysis[0].explanation
    if not why_it_fits:
        why_it_fits = _clean_text(selected_analysis.get("comparative_reason"))

    original_price = None
    if product.regular_price is not None and product.regular_price != product.price:
        original_price = _price_to_str(product.regular_price)

    availability_status = _clean_text(product.availability_status) or (
        "in_stock" if product.is_active else "unavailable"
    )
    is_available = bool(product.is_active) and (
        availability_status.lower() not in UNAVAILABLE_STATUSES
    )

    return ProductDetailOut(
        productId=_public_product_id(product),
        dbProductId=product.id,
        productName=product.name,
        brandName=brand_name,
        price=_price_to_str(product.price),
        originalPrice=original_price,
        currency=product.currency,
        shippingText=None,
        productImage=(
            ImageAssetOut(
                url=main_image_url,
                alt=image_alt,
                width=product.product_image_width,
                height=product.product_image_height,
            )
            if main_image_url
            else None
        ),
        additionalImages=additional_images,
        logoImage=(
            ImageAssetOut(url=logo_url, alt=f"{brand_name} logo")
            if logo_url and brand_name
            else None
        ),
        description=description,
        details=details,
        category=product.category,
        style=product.style,
        vibe=product.vibe,
        styleTags=style_tags,
        discoveryLabel=DISCOVERY_LABELS.get(product.city_connection_type),
        cityConnectionType=product.city_connection_type,
        cityConnectionLocation=product.city_connection_location,
        cityConnectionNote=product.city_connection_note,
        citySlug=product.city.slug if product.city else None,
        cityName=product.city.name if product.city else None,
        cityAnalysis=city_analysis,
        whyItFits=why_it_fits,
        affiliateUrl=product.affiliate_url,
        merchantUrl=product.merchant_url,
        isAffiliate=product.is_affiliate,
        merchantDestinationAvailable=bool(
            _clean_text(product.affiliate_url) or _clean_text(product.merchant_url)
        ),
        availabilityStatus=availability_status,
        isAvailable=is_available,
        isSaved=None,
    )


@router.get("", response_model=List[ProductCardOut])
def get_products(
    country: str | None = Query(
        None,
        description="ISO 3166-1 alpha-2 country code (e.g. BR). If provided, results are prioritized for that country.",
        min_length=2,
        max_length=2,
    ),
    city: str | None = Query(
        None,
        description="City slug or city name, e.g. new-york or New York.",
    ),
    brand_id: int | None = Query(None, description="Optional brand id filter."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Product)
        .join(Brand)
        .join(Country)
        .outerjoin(City, Product.city_id == City.id)
        .filter(Product.is_active.is_(True))
        .filter(Product.city_id.isnot(None))
        .filter(or_(Product.normalized_row_id.isnot(None), Product.source == "shopify"))
    )

    selected_city_slug = _normalize_city_slug(city)

    if selected_city_slug:
        query = query.filter(City.slug == selected_city_slug)

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    shoes_last = case(
        (func.lower(Product.category).in_(["shoe", "shoes", "sneaker", "sneakers", "footwear"]), 1),
        else_=0,
    )

    if country:
        c = country.upper()
        priority = case((Country.code == c, 0), else_=1)
        query = query.order_by(priority, shoes_last.asc(), Product.id.desc())
    else:
        query = query.order_by(shoes_last.asc(), Product.id.desc())

    products = query.offset(offset).limit(limit).all()
    return [_to_product_card(p) for p in products]


@router.get("/{product_id}", response_model=ProductDetailOut)
def get_product_detail(
    product_id: str,
    db: Session = Depends(get_db),
):
    product = _find_product(db, product_id)
    if not product or not product.city_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "product_not_found",
                "message": "This Haroona product could not be found.",
            },
        )

    detail = _to_product_detail(db, product)
    if not detail.isAvailable:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "product_unavailable",
                "message": "This product is no longer available.",
                "productId": detail.productId,
            },
        )

    return detail

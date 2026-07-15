from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.curation.candidate_queue import candidate_has_active_product
from app.models import Brand, City, Product, ProductCandidate
from app.utils.affiliate import is_affiliate


CATEGORY_ALIASES = {
    "dress": "dress",
    "dresses": "dress",
    "gown": "dress",
    "gowns": "dress",
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
    "set": "set",
    "sets": "set",
    "co-ord": "set",
    "co-ords": "set",
    "co ord": "set",
    "co ords": "set",
    "shoe": "shoe",
    "shoes": "shoe",
    "sneaker": "shoe",
    "sneakers": "shoe",
    "boot": "shoe",
    "boots": "shoe",
    "heel": "shoe",
    "heels": "shoe",
    "sandal": "shoe",
    "sandals": "shoe",
    "footwear": "shoe",
    "bag": "bags",
    "bags": "bags",
    "jewelry": "jewelry",
    "jewellery": "jewelry",
}

CATEGORY_INFERENCE_RULES = [
    (["dress", "gown"], "dress"),
    (["skirt", "trouser", "pant", "jean", "short"], "bottoms"),
    (["top", "blouse", "shirt", "vest", "tee", "t-shirt", "camisole", "tank"], "tops"),
    (["co-ord", "co ord", "set"], "set"),
    (["bag", "purse", "tote"], "bags"),
    (["shoe", "sandal", "boot", "heel"], "shoe"),
    (["necklace", "earring", "bracelet", "ring", "jewellery", "jewelry"], "jewelry"),
]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def _infer_category_from_text(value: str | None) -> str | None:
    haystack = (value or "").lower()

    for keywords, category in CATEGORY_INFERENCE_RULES:
        if any(keyword in haystack for keyword in keywords):
            return category

    return None


def _normalize_category(value: str | None, *, title: str | None = None) -> str | None:
    # A candidate can come from a mixed collection where the admin-entered
    # category hint was too broad. Trust obvious title words like "Top",
    # "Blouse", "Skirt", etc. over the stale hint before publishing.
    inferred_from_title = _infer_category_from_text(title)
    if inferred_from_title:
        return inferred_from_title

    cleaned = _clean(value)
    if not cleaned:
        return None

    normalized = cleaned.lower().replace("_", "-")
    return CATEGORY_ALIASES.get(normalized, normalized)


def _normalize_availability(value: str | None) -> str:
    cleaned = (value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned or "unknown"


def _require_publishable(candidate: ProductCandidate, city: City | None) -> None:
    if candidate.review_status != "approved":
        raise ValueError("Only approved candidates can be published")

    if not city:
        raise ValueError(f"City '{candidate.target_city_slug}' does not exist yet")

    if not _clean(candidate.title):
        raise ValueError("Candidate is missing a product title")

    if not (_clean(candidate.affiliate_url) or _clean(candidate.merchant_url)):
        raise ValueError("Candidate is missing a merchant or affiliate URL")

    if not _clean(candidate.image_url):
        raise ValueError("Candidate is missing a product image")

    if _normalize_availability(candidate.availability) != "in_stock":
        raise ValueError("Only in-stock candidates can be published")


def _get_or_create_brand(db: Session, name: str, country_id: int) -> Brand:
    brand = (
        db.query(Brand)
        .filter(Brand.name == name)
        .filter(Brand.country_id == country_id)
        .first()
    )

    if brand:
        return brand

    brand = Brand(name=name, country_id=country_id, logo_url=None)
    db.add(brand)
    db.flush()
    return brand


def _product_url(candidate: ProductCandidate) -> tuple[str | None, str | None, bool]:
    affiliate_url = _clean(candidate.affiliate_url)
    merchant_url = _clean(candidate.merchant_url)

    # Keep Product.affiliate_url populated because older product endpoints expect it,
    # but mark it as non-affiliate when the only available URL is the merchant URL.
    primary_url = affiliate_url or merchant_url
    is_aff = bool(affiliate_url and is_affiliate(affiliate_url))

    return primary_url, merchant_url, is_aff


def publish_product_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    published_by: str = "curator-studio",
) -> dict[str, Any]:
    city = db.query(City).filter(City.slug == candidate.target_city_slug).first()
    _require_publishable(candidate, city)

    assert city is not None  # Narrowed by _require_publishable.

    linked_product = None
    if candidate.promoted_product_id:
        linked_product = (
            db.query(Product)
            .filter(Product.id == candidate.promoted_product_id)
            .first()
        )
        if linked_product and linked_product.is_active:
            raise ValueError("Candidate is already published")

    brand_name = _clean(candidate.brand_name) or _clean(candidate.merchant_name) or "Haroona Curated"
    brand = _get_or_create_brand(db, brand_name, city.country_id)

    affiliate_url, merchant_url, is_aff = _product_url(candidate)
    now = datetime.now(timezone.utc)
    availability = _normalize_availability(candidate.availability)

    product = linked_product or (
        db.query(Product)
        .filter(Product.source == candidate.source)
        .filter(Product.external_id == candidate.external_product_id)
        .first()
    )
    action = "updated" if product else "created"

    if not product:
        product = Product(
            source=candidate.source,
            external_id=candidate.external_product_id,
            currency=candidate.currency or "USD",
            affiliate_url=affiliate_url,
            brand_id=brand.id,
        )
        db.add(product)

    product.advertiser_id = None
    product.name = candidate.title
    product.price = candidate.price_amount
    product.regular_price = candidate.price_amount
    product.currency = candidate.currency or "USD"
    product.affiliate_url = affiliate_url
    product.merchant_url = merchant_url
    product.is_affiliate = is_aff
    product.product_image_url = candidate.image_url
    product.product_image_alt = candidate.title
    product.brand_id = brand.id
    product.city_id = city.id
    product.category = _normalize_category(candidate.normalized_category, title=candidate.title)
    product.style = None
    product.vibe = None
    product.is_best_seller = candidate.haroona_score >= 95
    product.is_active = availability == "in_stock"
    product.city_connection_type = candidate.city_connection_type or "city_inspired_pick"
    product.city_connection_location = city.name
    product.city_connection_note = candidate.city_connection_note
    product.last_seen_at = now
    product.availability_status = availability
    product.last_price_checked_at = now
    product.price_check_status = "curator_publish"
    product.price_check_error = None

    if product.is_active:
        product.deactivated_at = None
        product.deactivation_reason = None
    else:
        product.deactivated_at = now
        product.deactivation_reason = f"candidate availability={availability}"

    db.flush()

    candidate.promoted_at = now
    candidate.promoted_product_id = product.id
    candidate.reviewed_by = published_by or candidate.reviewed_by

    db.commit()

    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "product_id": product.id,
        "action": action,
        "is_active": product.is_active,
        "promoted_at": candidate.promoted_at,
    }


def publish_approved_product_candidates(
    db: Session,
    *,
    target_city_slug: str | None = None,
    limit: int | None = None,
    published_by: str = "curator-studio",
) -> dict[str, Any]:
    query = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.review_status == "approved")
        .filter(~candidate_has_active_product())
        .order_by(ProductCandidate.haroona_score.desc(), ProductCandidate.id.desc())
    )

    if target_city_slug:
        query = query.filter(ProductCandidate.target_city_slug == target_city_slug)

    if limit is not None:
        query = query.limit(limit)

    candidates = query.all()
    results: list[dict[str, Any]] = []
    counts = {
        "created": 0,
        "updated": 0,
        "failed": 0,
        "published": 0,
    }

    for candidate in candidates:
        try:
            result = publish_product_candidate(
                db,
                candidate,
                published_by=published_by,
            )
            counts[result["action"]] += 1
            counts["published"] += 1
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - admin endpoint should report per-row failures.
            db.rollback()
            counts["failed"] += 1
            results.append(
                {
                    "status": "error",
                    "candidate_id": candidate.id,
                    "error": str(exc),
                }
            )

    return {
        "status": "ok" if counts["failed"] == 0 else "partial",
        "target_city_slug": target_city_slug,
        "checked": len(candidates),
        **counts,
        "items": results,
    }

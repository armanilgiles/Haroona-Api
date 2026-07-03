from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.scoring import score_city_fit
from app.models import ProductCandidate


USER_AGENT = (
    "Mozilla/5.0 (compatible; HaroonaCurator/0.1; +https://haroona.com) "
    "AppleWebKit/537.36"
)


@dataclass(frozen=True)
class CollectionScanOptions:
    source_url: str
    merchant_name: str
    target_city_slug: str = "london"
    normalized_category: str | None = None
    source: str = "shopify"
    source_type: str = "collection"
    limit: int = 30
    request_timeout_seconds: int = 20
    image_mode: str = "smart"
    scan_run_id: str | None = None


@dataclass(frozen=True)
class CandidatePayload:
    source: str
    source_type: str
    source_url: str
    scan_run_id: str | None
    merchant_name: str
    brand_name: str | None
    external_product_id: str
    title: str
    description: str | None
    price_amount: Decimal | None
    currency: str | None
    affiliate_url: str | None
    merchant_url: str | None
    image_url: str | None
    availability: str | None
    normalized_category: str | None
    target_city_slug: str
    city_connection_type: str | None
    city_connection_note: str | None
    haroona_score: int
    score_reasons: list[str]
    review_notes: str | None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _parse_decimal(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _clean_collection_source_url(source_url: str) -> str:
    parsed = urlparse(source_url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _collection_handle_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]

    try:
        collections_index = parts.index("collections")
    except ValueError as exc:
        raise ValueError("URL must contain /collections/{handle}") from exc

    if collections_index + 1 >= len(parts):
        raise ValueError("Collection URL is missing a collection handle")

    return parts[collections_index + 1].split(".")[0]


def _locale_prefix_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts and re.fullmatch(r"[a-z]{2}-[a-z]{2}", parts[0].lower()):
        return f"/{parts[0]}"
    return ""


def _json_endpoint_candidates(source_url: str) -> list[str]:
    source_url = _clean_collection_source_url(source_url)
    parsed = urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    handle = _collection_handle_from_url(source_url)
    locale_prefix = _locale_prefix_from_url(source_url)

    candidates = []
    if locale_prefix:
        candidates.append(f"{origin}{locale_prefix}/collections/{handle}/products.json?limit=250")
    candidates.append(f"{origin}/collections/{handle}/products.json?limit=250")
    return candidates


def _build_product_url(source_url: str, handle: str) -> str:
    source_url = _clean_collection_source_url(source_url)
    parsed = urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    locale_prefix = _locale_prefix_from_url(source_url)
    return f"{origin}{locale_prefix}/products/{handle}"


def _choose_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not variants:
        return None
    for variant in variants:
        if variant.get("available") is True:
            return variant
    return variants[0]


CATEGORY_INFERENCE_RULES = [
    (["dress", "gown"], "dress"),
    (["skirt"], "bottoms"),
    (["trouser", "pant", "jean", "short"], "bottoms"),
    (["top", "blouse", "shirt", "vest", "tee", "t-shirt", "camisole", "tank"], "tops"),
    (["co-ord", "co ord", "set"], "co-ords"),
    (["bag", "purse", "tote"], "bags"),
    (["shoe", "sandal", "boot", "heel"], "shoes"),
    (["necklace", "earring", "bracelet", "ring", "jewellery", "jewelry"], "jewelry"),
]


def _infer_category_from_text(title: str | None, product_type: str | None) -> str | None:
    haystack = f"{title or ''} {product_type or ''}".lower()

    for keywords, category in CATEGORY_INFERENCE_RULES:
        if any(keyword in haystack for keyword in keywords):
            return category

    return None


def _normalize_category(title: str, product_type: str | None, fallback: str | None) -> str | None:
    # Prefer the actual Shopify product title/type over the collection-level
    # category hint. A collection can contain a mix of dresses, skirts, and tops;
    # if the hint says "dresses" but the product is named "Sia Top", the product
    # should publish as Tops so the London filter appears dynamically.
    inferred_category = _infer_category_from_text(title, product_type)
    if inferred_category:
        return inferred_category

    if fallback:
        return fallback

    return None


def fetch_shopify_collection_products(options: CollectionScanOptions) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }

    last_error: Exception | None = None
    for endpoint in _json_endpoint_candidates(options.source_url):
        try:
            response = requests.get(
                endpoint,
                headers=headers,
                timeout=options.request_timeout_seconds,
            )
            if response.status_code >= 400:
                continue
            payload = response.json()
            products = payload.get("products")
            if isinstance(products, list):
                return products
        except Exception as exc:  # noqa: BLE001 - CLI should surface final failure cleanly
            last_error = exc

    if last_error:
        raise RuntimeError(f"Could not fetch Shopify collection JSON: {last_error}") from last_error

    raise RuntimeError("Could not fetch Shopify collection JSON from known endpoints")


def build_candidate_payloads(options: CollectionScanOptions) -> list[CandidatePayload]:
    products = fetch_shopify_collection_products(options)
    payloads: list[CandidatePayload] = []
    clean_source_url = _clean_collection_source_url(options.source_url)

    for product in products:
        title = (product.get("title") or "").strip()
        handle = (product.get("handle") or "").strip()
        external_id = str(product.get("id") or handle).strip()
        if not title or not external_id or not handle:
            continue

        variants = product.get("variants") or []
        variant = _choose_variant(variants)
        price_amount = _parse_decimal(variant.get("price") if variant else None)
        currency = "USD" if "/en-us/" in clean_source_url else None
        availability = "in_stock" if any(v.get("available") is True for v in variants) else "out_of_stock"

        images = product.get("images") or []
        image_url = None
        if images and isinstance(images[0], dict):
            image_url = images[0].get("src")

        description = _strip_html(product.get("body_html"))
        product_type = product.get("product_type")
        tags = product.get("tags") or []
        normalized_category = _normalize_category(title, product_type, options.normalized_category)

        score = score_city_fit(
            title=title,
            description=description,
            product_type=product_type,
            tags=tags if isinstance(tags, list) else [],
            target_city_slug=options.target_city_slug,
            normalized_category=normalized_category,
            merchant_name=options.merchant_name,
        )

        review_notes: list[str] = []
        if not image_url:
            review_notes.append("missing image")
        if price_amount is None:
            review_notes.append("missing price")
        if availability != "in_stock":
            review_notes.append("not in stock")
        if not normalized_category:
            review_notes.append("unknown category")

        payloads.append(
            CandidatePayload(
                source=options.source,
                source_type=options.source_type,
                source_url=clean_source_url,
                scan_run_id=options.scan_run_id,
                merchant_name=options.merchant_name,
                brand_name=product.get("vendor") or options.merchant_name,
                external_product_id=external_id,
                title=title,
                description=description,
                price_amount=price_amount,
                currency=currency,
                affiliate_url=None,
                merchant_url=_build_product_url(clean_source_url, handle),
                image_url=image_url,
                availability=availability,
                normalized_category=normalized_category,
                target_city_slug=options.target_city_slug,
                city_connection_type=score.city_connection_type,
                city_connection_note=score.city_connection_note,
                haroona_score=score.score,
                score_reasons=score.reasons,
                review_notes="; ".join(review_notes) or None,
            )
        )

    payloads.sort(key=lambda item: item.haroona_score, reverse=True)
    return payloads[: options.limit]


def _candidate_dedupe_key(payload: CandidatePayload) -> tuple[str, str]:
    return (payload.source, payload.external_product_id)


def _prefer_candidate_payload(current: CandidatePayload, incoming: CandidatePayload) -> CandidatePayload:
    if incoming.haroona_score > current.haroona_score:
        return incoming
    if incoming.haroona_score == current.haroona_score and incoming.image_url and not current.image_url:
        return incoming
    return current


def _dedupe_candidate_payloads(payloads: list[CandidatePayload]) -> tuple[list[CandidatePayload], int]:
    by_key: dict[tuple[str, str], CandidatePayload] = {}
    duplicate_count = 0

    for payload in payloads:
        key = _candidate_dedupe_key(payload)
        current = by_key.get(key)
        if current is None:
            by_key[key] = payload
            continue

        duplicate_count += 1
        by_key[key] = _prefer_candidate_payload(current, payload)

    return list(by_key.values()), duplicate_count


def _existing_candidates_by_key(
    db: Session,
    payloads: list[CandidatePayload],
) -> dict[tuple[str, str], ProductCandidate]:
    ids_by_source: dict[str, set[str]] = {}
    for payload in payloads:
        ids_by_source.setdefault(payload.source, set()).add(payload.external_product_id)

    existing: dict[tuple[str, str], ProductCandidate] = {}
    for source, external_ids in ids_by_source.items():
        if not external_ids:
            continue

        rows = (
            db.query(ProductCandidate)
            .filter(ProductCandidate.source == source)
            .filter(ProductCandidate.external_product_id.in_(external_ids))
            .all()
        )
        for row in rows:
            existing[(row.source, row.external_product_id)] = row

    return existing


def upsert_product_candidates(db: Session, payloads: list[CandidatePayload]) -> dict[str, int]:
    payloads, skipped_duplicates = _dedupe_candidate_payloads(payloads)
    existing_by_key = _existing_candidates_by_key(db, payloads)
    created = 0
    updated = 0

    for payload in payloads:
        key = _candidate_dedupe_key(payload)
        record = existing_by_key.get(key)

        if record:
            updated += 1
        else:
            record = ProductCandidate(
                source=payload.source,
                external_product_id=payload.external_product_id,
            )
            db.add(record)
            existing_by_key[key] = record
            created += 1

        record.source_type = payload.source_type
        record.source_url = payload.source_url
        record.scan_run_id = payload.scan_run_id
        record.merchant_name = payload.merchant_name
        record.brand_name = payload.brand_name
        record.title = payload.title
        record.description = payload.description
        record.price_amount = payload.price_amount
        record.currency = payload.currency
        record.affiliate_url = payload.affiliate_url
        record.merchant_url = payload.merchant_url
        record.image_url = payload.image_url or record.image_url
        record.availability = payload.availability
        record.normalized_category = payload.normalized_category
        record.target_city_slug = payload.target_city_slug
        record.city_connection_type = payload.city_connection_type
        record.city_connection_note = payload.city_connection_note
        record.haroona_score = payload.haroona_score
        record.score_reasons = payload.score_reasons
        record.review_notes = payload.review_notes

        if not record.review_status:
            record.review_status = "pending"

    db.commit()
    return {"created": created, "updated": updated, "skipped_duplicates": skipped_duplicates}


def scan_and_save_shopify_collection(db: Session, options: CollectionScanOptions) -> dict[str, Any]:
    payloads = build_candidate_payloads(options)
    counts = upsert_product_candidates(db, payloads)
    return {
        "status": "ok",
        "source_url": _clean_collection_source_url(options.source_url),
        "scan_run_id": options.scan_run_id,
        "merchant_name": options.merchant_name,
        "target_city_slug": options.target_city_slug,
        "image_mode": options.image_mode,
        "found": len(payloads),
        **counts,
        "items": [
            {
                "external_product_id": item.external_product_id,
                "title": item.title,
                "price_amount": str(item.price_amount) if item.price_amount is not None else None,
                "currency": item.currency,
                "merchant_url": item.merchant_url,
                "image_url": item.image_url,
                "availability": item.availability,
                "normalized_category": item.normalized_category,
                "city_connection_type": item.city_connection_type,
                "city_connection_note": item.city_connection_note,
                "haroona_score": item.haroona_score,
                "score_reasons": item.score_reasons,
                "review_notes": item.review_notes,
            }
            for item in payloads
        ],
    }

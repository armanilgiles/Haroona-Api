from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.eligibility import (
    add_reason_counts,
    blocking_reasons_only,
    evaluate_candidate_eligibility,
)
from app.curation.platform_alignment import (
    platform_alignment_passes,
    score_platform_alignment,
)
from app.curation.scoring import HYBRID_SCORING_VERSION, score_city_fit
from app.curation.shopify_image_selection import (
    ShopifyImageCandidate,
    ShopifyImageSelectionCache,
    image_candidates_from_shopify_product,
    normalize_image_mode,
    select_shopify_product_image,
)
from app.curation.storefront_discovery import (
    StorefrontDiscoveryError,
    discover_storefront_products,
)
from app.models import ProductCandidate


USER_AGENT = (
    "Mozilla/5.0 (compatible; HaroonaCurator/0.1; +https://haroona.com) "
    "AppleWebKit/537.36"
)
SHOPIFY_PAGE_SIZE = 250
SHOPIFY_PAGE_SIZE_FALLBACKS = (100, 50)
MAX_SHOPIFY_SOURCE_PRODUCTS = 500
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
TRANSIENT_RETRY_DELAYS_SECONDS = (0.25, 0.75)
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 300
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 3600
_HOST_RATE_LIMIT_UNTIL: dict[str, float] = {}


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
    merchant_verification: str = "unverified"
    merchant_profile_allowed: bool = False
    concept_overrides: tuple[dict[str, Any], ...] = ()


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
    merchant_verification: str
    merchant_profile_key: str | None
    eligibility_status: str
    eligibility_reasons: list[str]
    platform_alignment_score: Decimal | None
    platform_alignment_reasons: list[str]
    city_fit_score: int
    city_fit_scores: dict[str, int]
    secondary_city_slug: str | None
    scoring_confidence: int | None
    scoring_method: str
    scoring_version: str
    haroona_score: int
    score_reasons: list[str]
    review_notes: str | None


@dataclass(frozen=True)
class ShopifyFetchResult:
    products: list[dict[str, Any]]
    pages_scanned: int
    source_truncated: bool
    warnings: tuple[str, ...] = ()
    discovery_method: str = "shopify_collection_json"
    fallback_used: bool = False
    discovery_attempts: tuple[dict[str, str], ...] = ()


class CollectionDiscoveryError(RuntimeError):
    def __init__(self, message: str, *, attempts: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


class CollectionRateLimitedError(CollectionDiscoveryError):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int,
        attempts: list[dict[str, str]],
    ) -> None:
        super().__init__(message, attempts=attempts)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ShopifyCandidateDraft:
    payload: CandidatePayload
    image_candidates: list[ShopifyImageCandidate]
    product_type: str | None
    tags: list[str]


@dataclass(frozen=True)
class ShopifyBuildResult:
    payloads: list[CandidatePayload]
    discovered_count: int
    skipped_invalid_products: int
    skipped_ineligible_products: int
    ineligible_reason_counts: dict[str, int]
    skipped_missing_images: int
    skipped_due_to_limit: int
    pages_scanned: int
    source_truncated: bool
    image_candidates_checked: int
    warnings: tuple[str, ...] = ()
    discovery_method: str = "shopify_collection_json"
    fallback_used: bool = False
    discovery_attempts: tuple[dict[str, str], ...] = ()


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


def _clean_storefront_source_url(source_url: str) -> str:
    """Keep category filters needed by non-Shopify storefronts."""
    parsed = urlparse(source_url.strip())
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "")
    )


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


def _json_endpoint_candidates(
    source_url: str,
    *,
    page: int = 1,
    page_size: int = SHOPIFY_PAGE_SIZE,
) -> list[str]:
    source_url = _clean_collection_source_url(source_url)
    parsed = urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        handle = _collection_handle_from_url(source_url)
    except ValueError:
        return []
    locale_prefix = _locale_prefix_from_url(source_url)

    candidates = []
    if locale_prefix:
        candidates.append(
            f"{origin}{locale_prefix}/collections/{handle}/products.json"
            f"?limit={page_size}&page={page}"
        )
    candidates.append(
        f"{origin}/collections/{handle}/products.json"
        f"?limit={page_size}&page={page}"
    )
    return candidates


def _host_key(value: str) -> str:
    return (urlparse(value).hostname or "").lower()


def _parse_retry_after_seconds(value: str | None) -> int:
    cleaned = (value or "").strip()
    if cleaned.isdigit():
        return max(1, min(int(cleaned), MAX_RATE_LIMIT_COOLDOWN_SECONDS))
    if cleaned:
        try:
            retry_at = parsedate_to_datetime(cleaned)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
            return max(1, min(seconds, MAX_RATE_LIMIT_COOLDOWN_SECONDS))
        except (TypeError, ValueError, OverflowError):
            pass
    return DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS


def _rate_limit_remaining_seconds(value: str) -> int:
    host = _host_key(value)
    if not host:
        return 0
    remaining = int(_HOST_RATE_LIMIT_UNTIL.get(host, 0) - time.monotonic())
    if remaining <= 0:
        _HOST_RATE_LIMIT_UNTIL.pop(host, None)
        return 0
    return remaining


def _register_rate_limit(value: str, retry_after_header: str | None) -> int:
    seconds = _parse_retry_after_seconds(retry_after_header)
    host = _host_key(value)
    if host:
        _HOST_RATE_LIMIT_UNTIL[host] = max(
            _HOST_RATE_LIMIT_UNTIL.get(host, 0),
            time.monotonic() + seconds,
        )
    return seconds


def _request_shopify_json(
    endpoint: str,
    *,
    headers: dict[str, str],
    timeout_seconds: int,
) -> tuple[requests.Response | None, list[str]]:
    """Fetch one Shopify JSON page with bounded transient retries."""

    errors: list[str] = []
    total_attempts = len(TRANSIENT_RETRY_DELAYS_SECONDS) + 1
    for attempt_number in range(1, total_attempts + 1):
        try:
            response = requests.get(
                endpoint,
                headers=headers,
                timeout=timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            errors.append(f"attempt {attempt_number}: {type(exc).__name__}: {exc}")
            response = None
        except requests.RequestException as exc:
            errors.append(f"attempt {attempt_number}: {type(exc).__name__}: {exc}")
            return None, errors
        else:
            if response.status_code == 429:
                retry_after = _parse_retry_after_seconds(
                    response.headers.get("Retry-After")
                )
                errors.append(
                    f"attempt {attempt_number}: HTTP 429; retry after "
                    f"approximately {retry_after} seconds"
                )
                return response, errors
            if response.status_code not in TRANSIENT_HTTP_STATUSES:
                return response, errors
            errors.append(
                f"attempt {attempt_number}: HTTP {response.status_code}"
            )

        if attempt_number < total_attempts:
            time.sleep(TRANSIENT_RETRY_DELAYS_SECONDS[attempt_number - 1])

    return response, errors


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


def _fetch_shopify_collection_result(options: CollectionScanOptions) -> ShopifyFetchResult:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }

    discovery_attempts: list[dict[str, str]] = []
    cooldown_remaining = _rate_limit_remaining_seconds(options.source_url)
    if cooldown_remaining:
        discovery_attempts.append(
            {
                "method": "shopify_collection_json",
                "status": "rate_limited",
                "detail": (
                    "Haroona skipped a new storefront request because this host is "
                    f"cooling down for approximately {cooldown_remaining} more seconds."
                ),
            }
        )
        raise CollectionRateLimitedError(
            "The storefront is temporarily rate limiting automated catalog requests.",
            retry_after_seconds=cooldown_remaining,
            attempts=discovery_attempts,
        )
    selected_endpoint: str | None = None
    selected_page_size = SHOPIFY_PAGE_SIZE
    first_page_products: list[dict[str, Any]] | None = None
    page_sizes = (SHOPIFY_PAGE_SIZE, *SHOPIFY_PAGE_SIZE_FALLBACKS)
    json_endpoints = _json_endpoint_candidates(
        options.source_url,
        page=1,
        page_size=SHOPIFY_PAGE_SIZE,
    )
    if not json_endpoints:
        discovery_attempts.append(
            {
                "method": "shopify_collection_json",
                "status": "not_applicable",
                "detail": "The source URL does not expose a standard Shopify collection path.",
            }
        )

    for page_size in page_sizes:
        endpoints = _json_endpoint_candidates(
            options.source_url,
            page=1,
            page_size=page_size,
        )
        for endpoint in endpoints:
            try:
                response, request_errors = _request_shopify_json(
                    endpoint,
                    headers=headers,
                    timeout_seconds=options.request_timeout_seconds,
                )
                if response is None:
                    detail = "; ".join(request_errors) or "request failed"
                    raise requests.ConnectionError(detail)
                if response.status_code == 429:
                    retry_after_seconds = _register_rate_limit(
                        endpoint,
                        response.headers.get("Retry-After"),
                    )
                    discovery_attempts.append(
                        {
                            "method": "shopify_collection_json",
                            "status": "rate_limited",
                            "detail": (
                                f"The Shopify JSON endpoint returned HTTP 429. Haroona "
                                f"will avoid new requests to this host for approximately "
                                f"{retry_after_seconds} seconds."
                            ),
                        }
                    )
                    raise CollectionRateLimitedError(
                        "The storefront is temporarily rate limiting automated catalog requests.",
                        retry_after_seconds=retry_after_seconds,
                        attempts=discovery_attempts,
                    )
                if request_errors and response.status_code < 400:
                    discovery_attempts.append(
                        {
                            "method": "shopify_collection_json",
                            "status": "retried",
                            "detail": (
                                f"The {page_size}-product JSON request recovered after "
                                f"a transient failure: {'; '.join(request_errors)}."
                            ),
                        }
                    )
                if response.status_code >= 400:
                    discovery_attempts.append(
                        {
                            "method": "shopify_collection_json",
                            "status": "failed",
                            "detail": (
                                f"The {page_size}-product Shopify JSON endpoint returned "
                                f"HTTP {response.status_code}."
                            ),
                        }
                    )
                    continue
                payload = response.json()
                products = payload.get("products")
                if isinstance(products, list) and products:
                    selected_endpoint = endpoint
                    selected_page_size = page_size
                    first_page_products = products
                    discovery_attempts.append(
                        {
                            "method": "shopify_collection_json",
                            "status": "succeeded",
                            "detail": (
                                f"Found {len(products)} product record(s) on the first "
                                f"JSON page using a page size of {page_size}."
                            ),
                        }
                    )
                    break
                discovery_attempts.append(
                    {
                        "method": "shopify_collection_json",
                        "status": "no_data",
                        "detail": (
                            f"The {page_size}-product Shopify JSON endpoint did not "
                            "contain a non-empty products list."
                        ),
                    }
                )
            except CollectionRateLimitedError:
                raise
            except Exception as exc:  # noqa: BLE001 - surface final failure cleanly
                discovery_attempts.append(
                    {
                        "method": "shopify_collection_json",
                        "status": "failed",
                        "detail": (
                            f"The {page_size}-product Shopify JSON endpoint failed: {exc}"
                        ),
                    }
                )
        if selected_endpoint is not None:
            break

    if selected_endpoint is None or first_page_products is None:
        try:
            storefront_result = discover_storefront_products(
                _clean_storefront_source_url(options.source_url),
                headers=headers,
                timeout_seconds=options.request_timeout_seconds,
                max_products=max(options.limit * 4, 25),
            )
        except StorefrontDiscoveryError as exc:
            discovery_attempts.extend(attempt.as_dict() for attempt in exc.attempts)
            raise CollectionDiscoveryError(
                "Haroona could not discover products using Shopify JSON, embedded "
                "storefront data, or public product pages.",
                attempts=discovery_attempts,
            ) from exc

        discovery_attempts.extend(
            attempt.as_dict() for attempt in storefront_result.attempts
        )
        fallback_label = {
            "embedded_storefront_data": "embedded storefront data",
            "product_page_crawl": "public product pages",
        }.get(storefront_result.discovery_method, storefront_result.discovery_method)
        warnings = [
            "Shopify collection JSON was unavailable; "
            f"Haroona used {fallback_label} instead.",
            *storefront_result.warnings,
        ]
        return ShopifyFetchResult(
            products=storefront_result.products,
            pages_scanned=storefront_result.pages_scanned,
            source_truncated=storefront_result.source_truncated,
            warnings=tuple(warnings),
            discovery_method=storefront_result.discovery_method,
            fallback_used=True,
            discovery_attempts=tuple(discovery_attempts),
        )

    products: list[dict[str, Any]] = []
    seen_product_ids: set[str] = set()

    def append_unique(rows: list[dict[str, Any]]) -> None:
        for product in rows:
            product_id = str(product.get("id") or product.get("handle") or "").strip()
            dedupe_key = product_id or f"row:{len(products)}"
            if dedupe_key in seen_product_ids:
                continue
            seen_product_ids.add(dedupe_key)
            products.append(product)

    append_unique(first_page_products)
    pages_scanned = 1
    source_truncated = False
    warnings: list[str] = []

    current_page_products = first_page_products
    max_pages = max(
        (MAX_SHOPIFY_SOURCE_PRODUCTS + selected_page_size - 1) // selected_page_size,
        1,
    )
    for page in range(2, max_pages + 1):
        if len(current_page_products) < selected_page_size:
            break

        endpoint = re.sub(r"([?&])page=\d+", rf"\g<1>page={page}", selected_endpoint)
        try:
            response, request_errors = _request_shopify_json(
                endpoint,
                headers=headers,
                timeout_seconds=options.request_timeout_seconds,
            )
            if response is None:
                raise requests.ConnectionError(
                    "; ".join(request_errors) or "request failed"
                )
            response.raise_for_status()
            page_products = response.json().get("products")
            if not isinstance(page_products, list):
                raise ValueError("Shopify response did not contain a products list")
        except Exception as exc:  # noqa: BLE001 - return useful partial results
            source_truncated = True
            warnings.append(
                f"Shopify pagination stopped after page {pages_scanned}: {exc}."
            )
            break

        pages_scanned += 1
        current_page_products = page_products
        append_unique(page_products)

    if pages_scanned == max_pages and len(current_page_products) == selected_page_size:
        source_truncated = True
        warnings.append(
            f"The source scan stopped at {MAX_SHOPIFY_SOURCE_PRODUCTS} products; "
            "narrow the collection if you need to inspect later products."
        )

    return ShopifyFetchResult(
        products=products,
        pages_scanned=pages_scanned,
        source_truncated=source_truncated,
        warnings=tuple(warnings),
        discovery_method="shopify_collection_json",
        fallback_used=False,
        discovery_attempts=tuple(discovery_attempts),
    )


def fetch_shopify_collection_products(options: CollectionScanOptions) -> list[dict[str, Any]]:
    return _fetch_shopify_collection_result(options).products


def _build_candidate_draft(
    product: dict[str, Any],
    *,
    options: CollectionScanOptions,
    clean_source_url: str,
) -> ShopifyCandidateDraft | None:
    title = (product.get("title") or "").strip()
    handle = (product.get("handle") or "").strip()
    external_id = str(product.get("id") or handle).strip()
    if not title or not external_id or not handle:
        return None

    variants = product.get("variants") or []
    variant = _choose_variant(variants)
    price_amount = _parse_decimal(variant.get("price") if variant else None)
    currency = product.get("_currency") or (
        "USD" if "/en-us/" in clean_source_url else None
    )
    availability = (
        "in_stock"
        if any(v.get("available") is True for v in variants)
        else "out_of_stock"
    )

    description = _strip_html(product.get("body_html"))
    product_type = product.get("product_type")
    raw_tags = product.get("tags") or []
    tags = raw_tags if isinstance(raw_tags, list) else []
    normalized_category = _normalize_category(title, product_type, options.normalized_category)
    merchant_url = product.get("_merchant_url") or _build_product_url(
        clean_source_url,
        handle,
    )
    brand_name = product.get("vendor") or options.merchant_name

    score = score_city_fit(
        title=title,
        description=description,
        product_type=product_type,
        tags=tags,
        target_city_slug=options.target_city_slug,
        normalized_category=normalized_category,
        merchant_name=options.merchant_name,
        merchant_profile_allowed=options.merchant_profile_allowed,
        brand_name=brand_name,
        concept_overrides=options.concept_overrides,
    )
    eligibility = evaluate_candidate_eligibility(
        title=title,
        affiliate_url=None,
        merchant_url=merchant_url,
        image_url=None,
        availability=availability,
        normalized_category=normalized_category,
        price_amount=price_amount,
        currency=currency,
        require_image=False,
    )

    image_candidates = image_candidates_from_shopify_product(product)
    preliminary_platform_alignment = score_platform_alignment(
        title=title,
        description=description,
        product_type=product_type,
        tags=tags,
        merchant_name=options.merchant_name,
        brand_name=brand_name,
        merchant_verification=options.merchant_verification,
        image_url=image_candidates[0].url if image_candidates else None,
        image_quality_score=None,
        normalized_category=normalized_category,
        city_fit_score=score.score,
    )

    return ShopifyCandidateDraft(
        payload=CandidatePayload(
            source=options.source,
            source_type=options.source_type,
            source_url=clean_source_url,
            scan_run_id=options.scan_run_id,
            merchant_name=options.merchant_name,
            brand_name=brand_name,
            external_product_id=external_id,
            title=title,
            description=description,
            price_amount=price_amount,
            currency=currency,
            affiliate_url=None,
            merchant_url=merchant_url,
            image_url=None,
            availability=availability,
            normalized_category=normalized_category,
            target_city_slug=options.target_city_slug,
            city_connection_type=score.city_connection_type,
            city_connection_note=score.city_connection_note,
            merchant_verification=options.merchant_verification,
            merchant_profile_key=score.merchant_profile_key,
            eligibility_status=eligibility.status,
            eligibility_reasons=eligibility.reasons,
            platform_alignment_score=preliminary_platform_alignment.score,
            platform_alignment_reasons=preliminary_platform_alignment.reasons,
            city_fit_score=score.score,
            city_fit_scores=score.city_fit_scores or {options.target_city_slug: score.score},
            secondary_city_slug=score.secondary_city_slug,
            scoring_confidence=score.confidence,
            scoring_method="deterministic_rules",
            scoring_version=HYBRID_SCORING_VERSION,
            haroona_score=score.score,
            score_reasons=score.reasons,
            review_notes=(
                "; ".join(reason.replace("_", " ") for reason in eligibility.warning_reasons)
                or None
            ),
        ),
        image_candidates=image_candidates,
        product_type=product_type,
        tags=tags,
    )


def build_candidate_payload_result(options: CollectionScanOptions) -> ShopifyBuildResult:
    fetch_result = _fetch_shopify_collection_result(options)
    clean_source_url = _clean_collection_source_url(options.source_url)
    drafts: list[ShopifyCandidateDraft] = []
    skipped_invalid_products = 0
    skipped_ineligible_products = 0
    ineligible_reason_counts: dict[str, int] = {}

    for product in fetch_result.products:
        draft = _build_candidate_draft(
            product,
            options=options,
            clean_source_url=clean_source_url,
        )
        if draft is None:
            skipped_invalid_products += 1
            continue
        if draft.payload.eligibility_status == "ineligible":
            skipped_ineligible_products += 1
            add_reason_counts(
                ineligible_reason_counts,
                blocking_reasons_only(draft.payload.eligibility_reasons),
            )
            continue
        drafts.append(draft)

    drafts.sort(key=lambda item: candidate_review_rank(item.payload), reverse=True)
    payloads: list[CandidatePayload] = []
    skipped_missing_images = 0
    image_candidates_checked = 0
    selection_cache = ShopifyImageSelectionCache()

    for draft in drafts:
        if len(payloads) >= options.limit:
            break

        selection = select_shopify_product_image(
            draft.image_candidates,
            image_mode=options.image_mode,
            referer=clean_source_url,
            timeout_seconds=options.request_timeout_seconds,
            cache=selection_cache,
        )
        image_candidates_checked += selection.candidates_checked
        if not selection.url:
            skipped_missing_images += 1
            continue

        eligibility = evaluate_candidate_eligibility(
            title=draft.payload.title,
            affiliate_url=draft.payload.affiliate_url,
            merchant_url=draft.payload.merchant_url,
            image_url=selection.url,
            availability=draft.payload.availability,
            normalized_category=draft.payload.normalized_category,
            price_amount=draft.payload.price_amount,
            currency=draft.payload.currency,
        )
        platform_alignment = score_platform_alignment(
            title=draft.payload.title,
            description=draft.payload.description,
            product_type=draft.product_type,
            tags=draft.tags,
            merchant_name=draft.payload.merchant_name,
            brand_name=draft.payload.brand_name,
            merchant_verification=draft.payload.merchant_verification,
            image_url=selection.url,
            image_quality_score=selection.score,
            normalized_category=draft.payload.normalized_category,
            city_fit_score=draft.payload.city_fit_score,
        )
        payloads.append(
            replace(
                draft.payload,
                image_url=selection.url,
                eligibility_status=eligibility.status,
                eligibility_reasons=eligibility.reasons,
                platform_alignment_score=platform_alignment.score,
                platform_alignment_reasons=platform_alignment.reasons,
            )
        )

    reviewed_draft_count = len(payloads) + skipped_missing_images
    return ShopifyBuildResult(
        payloads=payloads,
        discovered_count=len(fetch_result.products),
        skipped_invalid_products=skipped_invalid_products,
        skipped_ineligible_products=skipped_ineligible_products,
        ineligible_reason_counts=ineligible_reason_counts,
        skipped_missing_images=skipped_missing_images,
        skipped_due_to_limit=max(len(drafts) - reviewed_draft_count, 0),
        pages_scanned=fetch_result.pages_scanned,
        source_truncated=fetch_result.source_truncated,
        image_candidates_checked=image_candidates_checked,
        warnings=fetch_result.warnings,
        discovery_method=fetch_result.discovery_method,
        fallback_used=fetch_result.fallback_used,
        discovery_attempts=fetch_result.discovery_attempts,
    )


def build_candidate_payloads(options: CollectionScanOptions) -> list[CandidatePayload]:
    return build_candidate_payload_result(options).payloads


def candidate_review_rank(payload: CandidatePayload) -> tuple[int, Decimal, int]:
    platform_score = payload.platform_alignment_score or Decimal("0")
    return (
        1 if platform_alignment_passes(platform_score) else 0,
        platform_score,
        payload.city_fit_score,
    )


def _cached_candidate_payload(
    record: ProductCandidate,
    *,
    options: CollectionScanOptions,
) -> CandidatePayload:
    score = score_city_fit(
        title=record.title,
        description=record.description,
        product_type=record.normalized_category,
        tags=[],
        target_city_slug=options.target_city_slug,
        normalized_category=record.normalized_category or options.normalized_category,
        merchant_name=options.merchant_name,
        merchant_profile_allowed=options.merchant_profile_allowed,
        brand_name=record.brand_name,
        concept_overrides=options.concept_overrides,
    )
    eligibility = evaluate_candidate_eligibility(
        title=record.title,
        affiliate_url=record.affiliate_url,
        merchant_url=record.merchant_url,
        image_url=record.image_url,
        availability=record.availability,
        normalized_category=record.normalized_category or options.normalized_category,
        price_amount=record.price_amount,
        currency=record.currency,
    )
    platform_score = record.platform_alignment_score
    platform_reasons = list(record.platform_alignment_reasons or [])
    if platform_score is None:
        platform = score_platform_alignment(
            title=record.title,
            description=record.description,
            product_type=record.normalized_category,
            tags=[],
            merchant_name=options.merchant_name,
            brand_name=record.brand_name,
            merchant_verification=options.merchant_verification,
            image_url=record.image_url,
            image_quality_score=None,
            normalized_category=record.normalized_category or options.normalized_category,
            city_fit_score=score.score,
        )
        platform_score = platform.score
        platform_reasons = platform.reasons

    return CandidatePayload(
        source=record.source,
        source_type=record.source_type,
        source_url=_clean_collection_source_url(options.source_url),
        scan_run_id=options.scan_run_id,
        merchant_name=options.merchant_name,
        brand_name=record.brand_name,
        external_product_id=record.external_product_id,
        title=record.title,
        description=record.description,
        price_amount=record.price_amount,
        currency=record.currency,
        affiliate_url=record.affiliate_url,
        merchant_url=record.merchant_url,
        image_url=record.image_url,
        availability=record.availability,
        normalized_category=record.normalized_category or options.normalized_category,
        target_city_slug=options.target_city_slug,
        city_connection_type=score.city_connection_type,
        city_connection_note=score.city_connection_note,
        merchant_verification=options.merchant_verification,
        merchant_profile_key=score.merchant_profile_key,
        eligibility_status=eligibility.status,
        eligibility_reasons=eligibility.reasons,
        platform_alignment_score=platform_score,
        platform_alignment_reasons=platform_reasons,
        city_fit_score=score.score,
        city_fit_scores=score.city_fit_scores or {options.target_city_slug: score.score},
        secondary_city_slug=score.secondary_city_slug,
        scoring_confidence=score.confidence,
        scoring_method="deterministic_rules",
        scoring_version=HYBRID_SCORING_VERSION,
        haroona_score=score.score,
        score_reasons=score.reasons,
        review_notes=record.review_notes,
    )


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
    from app.curation.affiliate_links import (
        AFFILIATE_FAILED,
        AFFILIATE_GENERATED,
        AFFILIATE_VERIFIED,
        reset_affiliate_link_after_product_url_change,
    )

    payloads, skipped_duplicates = _dedupe_candidate_payloads(payloads)
    existing_by_key = _existing_candidates_by_key(db, payloads)
    created = 0
    updated = 0

    for payload in payloads:
        key = _candidate_dedupe_key(payload)
        record = existing_by_key.get(key)

        is_existing = record is not None
        previous_merchant_url = (
            (record.merchant_url or "").strip() if record is not None else None
        )

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
        next_merchant_url = (payload.merchant_url or "").strip() or None
        product_url_changed = (
            is_existing
            and previous_merchant_url is not None
            and next_merchant_url is not None
            and previous_merchant_url != next_merchant_url
        )
        if product_url_changed:
            reset_affiliate_link_after_product_url_change(record)
        elif not is_existing or (
            (record.affiliate_link_status or "not_requested")
            not in {AFFILIATE_GENERATED, AFFILIATE_VERIFIED, AFFILIATE_FAILED}
        ):
            record.affiliate_url = payload.affiliate_url
        record.merchant_url = payload.merchant_url
        record.image_url = payload.image_url or record.image_url
        record.availability = payload.availability
        record.normalized_category = payload.normalized_category
        record.target_city_slug = payload.target_city_slug
        record.city_connection_type = payload.city_connection_type
        record.city_connection_note = payload.city_connection_note
        record.merchant_verification = payload.merchant_verification
        record.merchant_profile_key = payload.merchant_profile_key
        record.eligibility_status = payload.eligibility_status
        record.eligibility_reasons = payload.eligibility_reasons
        record.platform_alignment_score = payload.platform_alignment_score
        record.platform_alignment_reasons = payload.platform_alignment_reasons
        record.city_fit_score = payload.city_fit_score
        record.city_fit_scores = payload.city_fit_scores
        record.secondary_city_slug = payload.secondary_city_slug
        record.scoring_confidence = payload.scoring_confidence
        record.scoring_method = payload.scoring_method
        record.scoring_version = payload.scoring_version
        record.haroona_score = payload.haroona_score
        record.score_reasons = payload.score_reasons
        record.review_notes = payload.review_notes

        if not record.review_status:
            record.review_status = "pending"

    db.commit()
    return {"created": created, "updated": updated, "skipped_duplicates": skipped_duplicates}


def build_scan_summary(
    *,
    requested_limit: int,
    discovered_count: int,
    selected_count: int,
    created_count: int,
    updated_count: int,
    skipped_duplicates: int = 0,
    skipped_missing_images: int = 0,
    skipped_invalid_products: int = 0,
    skipped_ineligible_products: int = 0,
    ineligible_reason_counts: dict[str, int] | None = None,
    skipped_due_to_limit: int = 0,
    image_mode: str | None = None,
    pages_scanned: int | None = None,
    source_truncated: bool = False,
    image_candidates_checked: int | None = None,
    discovery_method: str | None = None,
    fallback_used: bool = False,
    discovery_attempts: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    saved_count = created_count + updated_count
    skipped_total = (
        skipped_duplicates
        + skipped_missing_images
        + skipped_invalid_products
        + skipped_ineligible_products
        + skipped_due_to_limit
    )

    message_parts = [
        f"saved {saved_count} candidate{'s' if saved_count != 1 else ''}",
        f"{created_count} new",
        f"{updated_count} updated",
    ]
    if skipped_total:
        message_parts.append(f"{skipped_total} skipped")
    if image_mode:
        message_parts.append(f"{image_mode.replace('_', '-')} mode")

    summary = {
        "requested_limit": requested_limit,
        "discovered": discovered_count,
        "selected_for_review": selected_count,
        "saved": saved_count,
        "created": created_count,
        "updated": updated_count,
        "skipped_total": skipped_total,
        "skipped": {
            "duplicates": skipped_duplicates,
            "missing_or_unverified_images": skipped_missing_images,
            "invalid_products": skipped_invalid_products,
            "ineligible_products": skipped_ineligible_products,
            "over_limit": skipped_due_to_limit,
        },
        "ineligible_reasons": ineligible_reason_counts or {},
        "message": "Scan " + " · ".join(message_parts) + ".",
    }
    if pages_scanned is not None:
        summary["pages_scanned"] = pages_scanned
    if image_candidates_checked is not None:
        summary["image_candidates_checked"] = image_candidates_checked
    if discovery_method:
        summary["discovery"] = {
            "method": discovery_method,
            "fallback_used": fallback_used,
            "attempts": list(discovery_attempts),
        }
    summary["source_truncated"] = source_truncated
    return summary


def _candidate_item_payload(item: CandidatePayload) -> dict[str, Any]:
    return {
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
        "merchant_verification": item.merchant_verification,
        "merchant_profile_key": item.merchant_profile_key,
        "eligibility_status": item.eligibility_status,
        "eligibility_reasons": item.eligibility_reasons,
        "platform_alignment_score": (
            str(item.platform_alignment_score)
            if item.platform_alignment_score is not None
            else None
        ),
        "platform_alignment_reasons": item.platform_alignment_reasons,
        "city_fit_score": item.city_fit_score,
        "city_fit_scores": item.city_fit_scores,
        "secondary_city_slug": item.secondary_city_slug,
        "scoring_confidence": item.scoring_confidence,
        "scoring_method": item.scoring_method,
        "scoring_version": item.scoring_version,
        "haroona_score": item.haroona_score,
        "score_reasons": item.score_reasons,
        "review_notes": item.review_notes,
    }


def _scan_saved_snapshot_after_rate_limit(
    db: Session,
    options: CollectionScanOptions,
    error: CollectionRateLimitedError,
) -> dict[str, Any] | None:
    clean_source_url = _clean_collection_source_url(options.source_url)
    cached_rows = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.source == options.source)
        .filter(ProductCandidate.source_url == clean_source_url)
        .order_by(ProductCandidate.updated_at.desc(), ProductCandidate.id.desc())
        .all()
    )
    if not cached_rows:
        return None

    eligible_payloads: list[CandidatePayload] = []
    skipped_ineligible = 0
    ineligible_reason_counts: dict[str, int] = {}
    for record in cached_rows:
        payload = _cached_candidate_payload(record, options=options)
        if payload.eligibility_status == "ineligible":
            skipped_ineligible += 1
            add_reason_counts(
                ineligible_reason_counts,
                blocking_reasons_only(payload.eligibility_reasons),
            )
            continue
        eligible_payloads.append(payload)

    eligible_payloads.sort(key=candidate_review_rank, reverse=True)
    payloads = eligible_payloads[: options.limit]
    if not payloads:
        return None

    counts = upsert_product_candidates(db, payloads)
    attempts = (
        *error.attempts,
        {
            "method": "cached_product_candidates",
            "status": "succeeded",
            "detail": (
                f"Reused and rescored {len(cached_rows)} product(s) from the last "
                "successful scan of this exact collection URL."
            ),
        },
    )
    warning = (
        "The storefront returned HTTP 429, so Haroona did not make additional "
        "storefront requests. It reused previously saved product data and recalculated "
        f"the {options.target_city_slug.replace('-', ' ').title()} scores. Prices, "
        "availability, and images are from the last successful source scan."
    )
    summary = build_scan_summary(
        requested_limit=options.limit,
        discovered_count=len(cached_rows),
        selected_count=len(payloads),
        created_count=counts["created"],
        updated_count=counts["updated"],
        skipped_duplicates=counts["skipped_duplicates"],
        skipped_ineligible_products=skipped_ineligible,
        ineligible_reason_counts=ineligible_reason_counts,
        skipped_due_to_limit=max(len(eligible_payloads) - len(payloads), 0),
        image_mode=normalize_image_mode(options.image_mode),
        pages_scanned=0,
        source_truncated=True,
        image_candidates_checked=0,
        discovery_method="cached_product_candidates",
        fallback_used=True,
        discovery_attempts=attempts,
    )
    summary["message"] = (
        f"Cached scan saved {len(payloads)} candidate"
        f"{'s' if len(payloads) != 1 else ''} · {counts['created']} new · "
        f"{counts['updated']} updated · fresh source temporarily rate limited."
    )
    return {
        "status": "ok",
        "source_url": clean_source_url,
        "scan_run_id": options.scan_run_id,
        "merchant_name": options.merchant_name,
        "target_city_slug": options.target_city_slug,
        "image_mode": normalize_image_mode(options.image_mode),
        "found": len(payloads),
        **counts,
        "summary": summary,
        "discovery": summary.get("discovery"),
        "warnings": [warning],
        "items": [_candidate_item_payload(item) for item in payloads],
    }


def scan_and_save_shopify_collection(db: Session, options: CollectionScanOptions) -> dict[str, Any]:
    try:
        build_result = build_candidate_payload_result(options)
    except CollectionRateLimitedError as exc:
        cached_result = _scan_saved_snapshot_after_rate_limit(db, options, exc)
        if cached_result is not None:
            return cached_result
        raise
    payloads = build_result.payloads
    counts = upsert_product_candidates(db, payloads)
    summary = build_scan_summary(
        requested_limit=options.limit,
        discovered_count=build_result.discovered_count,
        selected_count=len(payloads),
        created_count=counts["created"],
        updated_count=counts["updated"],
        skipped_duplicates=counts["skipped_duplicates"],
        skipped_missing_images=build_result.skipped_missing_images,
        skipped_invalid_products=build_result.skipped_invalid_products,
        skipped_ineligible_products=build_result.skipped_ineligible_products,
        ineligible_reason_counts=build_result.ineligible_reason_counts,
        skipped_due_to_limit=build_result.skipped_due_to_limit,
        image_mode=normalize_image_mode(options.image_mode),
        pages_scanned=build_result.pages_scanned,
        source_truncated=build_result.source_truncated,
        image_candidates_checked=build_result.image_candidates_checked,
        discovery_method=build_result.discovery_method,
        fallback_used=build_result.fallback_used,
        discovery_attempts=build_result.discovery_attempts,
    )
    return {
        "status": "ok",
        "source_url": _clean_collection_source_url(options.source_url),
        "scan_run_id": options.scan_run_id,
        "merchant_name": options.merchant_name,
        "target_city_slug": options.target_city_slug,
        "image_mode": normalize_image_mode(options.image_mode),
        "found": len(payloads),
        **counts,
        "summary": summary,
        "discovery": summary.get("discovery"),
        "warnings": list(build_result.warnings),
        "items": [_candidate_item_payload(item) for item in payloads],
    }

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.city_assignment import CityScanMode, normalize_city_scan_mode
from app.curation.shopify_collection import (
    CollectionScanOptions,
    build_candidate_payload_from_product,
    build_scan_summary,
    upsert_product_candidates,
)
from app.curation.source_scan_guardrails import get_merchant_source_guidance
from app.curation.storefront_discovery import (
    extract_product_from_meta,
    extract_storefront_page,
    product_from_mapping,
)
from app.models import ProductCandidate


USER_AGENT = (
    "Mozilla/5.0 (compatible; HaroonaCurator/0.1; +https://haroona.com) "
    "AppleWebKit/537.36"
)
MAX_PRODUCT_PAGE_BYTES = 5_000_000
MAX_REDIRECTS = 5
REQUEST_TIMEOUT_SECONDS = 20
_PRODUCT_PATH_PATTERN = re.compile(
    r"/(?:products?|product-detail|p|item|goods?)/[^/?#]+|/[^/?#]+\.html/?$",
    re.IGNORECASE,
)
_COLLECTION_PATH_PATTERN = re.compile(
    r"/(?:collections?|categories?|search|catalog)(?:/|$)",
    re.IGNORECASE,
)


class SingleProductImportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: Iterable[dict[str, str]] = (),
    ) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


class ProductUrlValidationError(SingleProductImportError):
    pass


class ProductPageFetchError(SingleProductImportError):
    pass


class NotProductPageError(SingleProductImportError):
    pass


@dataclass(frozen=True)
class SingleProductPage:
    canonical_url: str
    product: dict[str, Any]
    discovery_method: str
    attempts: tuple[dict[str, str], ...]


def _normalized_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ProductUrlValidationError(
            "Use a complete public product URL beginning with http:// or https://."
        )
    if parsed.username or parsed.password:
        raise ProductUrlValidationError(
            "Product URLs cannot contain embedded credentials."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProductUrlValidationError("The product URL contains an invalid port.") from exc
    if port not in {None, 80, 443}:
        raise ProductUrlValidationError(
            "Product URLs must use the standard HTTP or HTTPS port."
        )

    host = parsed.hostname.lower().rstrip(".")
    netloc = host
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    return urlunparse(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )


def _assert_public_host(url: str) -> str:
    normalized = _normalized_url(url)
    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ProductUrlValidationError(
            "The product URL must point to a public retailer website."
        )

    try:
        literal_address = ipaddress.ip_address(host)
        addresses = {literal_address}
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ProductUrlValidationError(
                "The retailer domain could not be resolved."
            ) from exc
        addresses = {
            ipaddress.ip_address(item[4][0].split("%", 1)[0])
            for item in resolved
        }

    if not addresses or any(not address.is_global for address in addresses):
        raise ProductUrlValidationError(
            "The product URL must resolve only to public internet addresses."
        )
    return normalized


def _safe_embedded_asset_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(
            (".localhost", ".local", ".internal")
        ):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True
        return address.is_global
    except ValueError:
        return False


def _read_response_body(response: requests.Response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_PRODUCT_PAGE_BYTES:
                raise ProductPageFetchError(
                    "The retailer page is too large to analyze safely."
                )
        except ValueError:
            pass

    body = response.content
    if len(body) > MAX_PRODUCT_PAGE_BYTES:
        raise ProductPageFetchError(
            "The retailer page is too large to analyze safely."
        )
    return body


def _fetch_public_document(
    url: str,
    *,
    accept: str,
    method_name: str,
) -> tuple[bytes, str, str, list[dict[str, str]]]:
    current_url = url
    attempts: list[dict[str, str]] = []

    for _ in range(MAX_REDIRECTS + 1):
        current_url = _assert_public_host(current_url)
        try:
            response = requests.get(
                current_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": accept,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            attempts.append(
                {
                    "method": method_name,
                    "status": "failed",
                    "detail": f"The retailer page request failed: {type(exc).__name__}.",
                }
            )
            raise ProductPageFetchError(
                "Haroona could not fetch the retailer product page.",
                attempts=attempts,
            ) from exc

        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            if not location:
                attempts.append(
                    {
                        "method": method_name,
                        "status": "failed",
                        "detail": "The retailer returned a redirect without a destination.",
                    }
                )
                raise ProductPageFetchError(
                    "The retailer returned an invalid redirect.",
                    attempts=attempts,
                )
            attempts.append(
                {
                    "method": method_name,
                    "status": "redirected",
                    "detail": "The retailer redirected to its canonical page URL.",
                }
            )
            current_url = urljoin(current_url, location)
            continue

        if response.status_code >= 400:
            attempts.append(
                {
                    "method": method_name,
                    "status": "failed",
                    "detail": f"The retailer returned HTTP {response.status_code}.",
                }
            )
            raise ProductPageFetchError(
                f"The retailer returned HTTP {response.status_code} for this URL.",
                attempts=attempts,
            )

        body = _read_response_body(response)
        content_type = response.headers.get("Content-Type", "").lower()
        attempts.append(
            {
                "method": method_name,
                "status": "succeeded",
                "detail": "The public retailer page was fetched.",
            }
        )
        return body, content_type, current_url, attempts

    attempts.append(
        {
            "method": method_name,
            "status": "failed",
            "detail": "The retailer exceeded the redirect limit.",
        }
    )
    raise ProductPageFetchError(
        "The retailer redirected too many times.",
        attempts=attempts,
    )


def _product_from_json_document(
    document: Any,
    *,
    base_url: str,
) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        return None
    raw_product = document.get("product")
    explicitly_wrapped = isinstance(raw_product, dict)
    if explicitly_wrapped:
        document = raw_product
    schema_type = document.get("@type")
    schema_types = (
        {str(item).lower() for item in schema_type}
        if isinstance(schema_type, list)
        else {str(schema_type or "").lower()}
    )
    has_product_shape = "product" in schema_types or any(
        key in document
        for key in (
            "handle",
            "variants",
            "offers",
            "productUrl",
            "product_url",
            "featured_image",
            "featuredImage",
        )
    )
    if not explicitly_wrapped and not has_product_shape:
        return None
    return product_from_mapping(
        document,
        base_url=base_url,
        assume_shopify_cents=True,
    )


def _comparison_key(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    path = re.sub(r"\.(?:json|js)$", "", path, flags=re.IGNORECASE)
    return host, path


def _product_matches_page(product: dict[str, Any], page_url: str) -> bool:
    merchant_url = str(product.get("_merchant_url") or "").strip()
    return bool(
        merchant_url
        and _comparison_key(merchant_url) == _comparison_key(page_url)
    )


def _product_richness(product: dict[str, Any]) -> int:
    return sum(
        1
        for key in (
            "title",
            "vendor",
            "body_html",
            "variants",
            "images",
            "_currency",
            "_merchant_url",
        )
        if product.get(key)
    )


def _decode_document(body: bytes, content_type: str) -> str:
    match = re.search(r"charset=([^\s;]+)", content_type)
    charset = match.group(1).strip("\"'") if match else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _shopify_fallback_urls(page_url: str) -> tuple[str, ...]:
    parsed = urlparse(page_url)
    if not _PRODUCT_PATH_PATTERN.search(parsed.path):
        return ()
    base_path = re.sub(
        r"\.(?:json|js)$",
        "",
        parsed.path.rstrip("/"),
        flags=re.IGNORECASE,
    )
    return tuple(
        urlunparse((parsed.scheme, parsed.netloc, f"{base_path}{suffix}", "", "", ""))
        for suffix in (".js", ".json")
    )


def fetch_single_product_page(url: str) -> SingleProductPage:
    body, content_type, final_url, attempts = _fetch_public_document(
        url,
        accept="text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        method_name="single_product_page",
    )

    if "json" in content_type:
        try:
            document = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NotProductPageError(
                "The URL returned JSON, but it was not usable product data.",
                attempts=attempts,
            ) from exc
        product = _product_from_json_document(document, base_url=final_url)
        if product:
            product["_merchant_url"] = final_url
            return SingleProductPage(
                canonical_url=final_url,
                product=product,
                discovery_method="single_product_json",
                attempts=tuple(attempts),
            )

    html = _decode_document(body, content_type)
    extraction = extract_storefront_page(html, base_url=final_url)
    exact_products = [
        product
        for product in extraction.products
        if _product_matches_page(product, final_url)
    ]
    if exact_products:
        product = max(exact_products, key=_product_richness)
        product["_merchant_url"] = final_url
        return SingleProductPage(
            canonical_url=final_url,
            product=product,
            discovery_method="single_product_structured_data",
            attempts=tuple(attempts),
        )

    meta_product = extract_product_from_meta(html, product_url=final_url)
    if meta_product:
        meta_product["_merchant_url"] = final_url
        return SingleProductPage(
            canonical_url=final_url,
            product=meta_product,
            discovery_method="single_product_meta_tags",
            attempts=tuple(attempts),
        )

    path = urlparse(final_url).path
    looks_like_product_path = bool(_PRODUCT_PATH_PATTERN.search(path))
    looks_like_collection_path = bool(_COLLECTION_PATH_PATTERN.search(path))
    if (
        looks_like_product_path
        and not looks_like_collection_path
        and len(extraction.products) == 1
    ):
        product = extraction.products[0]
        product["_merchant_url"] = final_url
        return SingleProductPage(
            canonical_url=final_url,
            product=product,
            discovery_method="single_product_embedded_data",
            attempts=tuple(attempts),
        )

    for fallback_url in _shopify_fallback_urls(final_url):
        try:
            fallback_body, fallback_type, _, fallback_attempts = (
                _fetch_public_document(
                    fallback_url,
                    accept="application/json,*/*;q=0.8",
                    method_name="single_product_shopify_json",
                )
            )
        except SingleProductImportError as exc:
            attempts.extend(exc.attempts)
            continue
        attempts.extend(fallback_attempts)
        try:
            document = json.loads(_decode_document(fallback_body, fallback_type))
        except json.JSONDecodeError:
            continue
        product = _product_from_json_document(document, base_url=final_url)
        if product:
            product["_merchant_url"] = final_url
            return SingleProductPage(
                canonical_url=final_url,
                product=product,
                discovery_method="single_product_shopify_json",
                attempts=tuple(attempts),
            )

    attempts.append(
        {
            "method": "product_page_validation",
            "status": "failed",
            "detail": (
                "No page-level Product structured data or product metadata "
                "matched the submitted URL."
            ),
        }
    )
    raise NotProductPageError(
        "This URL does not appear to be an individual product-detail page.",
        attempts=attempts,
    )


def merchant_name_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label]
    candidate_labels = [
        label
        for label in labels[:-1]
        if label not in {"www", "shop", "store", "global", "us", "uk", "en"}
    ]
    candidate = candidate_labels[-1] if candidate_labels else (labels[0] if labels else "Retailer")
    provisional = re.sub(r"[-_]+", " ", candidate).strip().title() or "Retailer"
    guidance = get_merchant_source_guidance(url, provisional)
    if guidance.verification == "conflict" and guidance.suggested_name:
        return guidance.suggested_name
    return provisional


def _stable_external_product_id(url: str) -> str:
    normalized = _normalized_url(url)
    parsed = urlparse(normalized)
    product_identity_url = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
    )
    return hashlib.sha256(product_identity_url.encode("utf-8")).hexdigest()[:48]


def _clean_explanation(item: dict[str, Any]) -> str:
    analysis = item.get("scoring_analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    possible_reasons = [
        analysis.get("comparative_reason"),
        *(item.get("score_reasons") or []),
        item.get("city_connection_note"),
    ]
    for value in possible_reasons:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if not cleaned or cleaned.lower().startswith("verdict:"):
            continue
        if len(cleaned) > 240:
            cleaned = cleaned[:237].rstrip(" ,;:-") + "..."
        return cleaned
    return (
        f"Haroona's garment evidence produced a {int(item.get('score') or 0)}/100 "
        "city match."
    )


def _recommendations(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for item in sorted(
        candidates,
        key=lambda candidate: int(candidate.get("rank") or 999),
    )[:3]:
        city_slug = str(item.get("city_slug") or "")
        recommendations.append(
            {
                "city_id": city_slug,
                "city_slug": city_slug,
                "rank": int(item.get("rank") or len(recommendations) + 1),
                "score": int(item.get("score") or 0),
                "city_fit_score": int(
                    item.get("city_fit_score") or item.get("score") or 0
                ),
                "confidence": item.get("confidence"),
                "primary_match_eligible": item.get("primary_match_eligible"),
                "match_type": item.get("match_type"),
                "explanation": _clean_explanation(item),
            }
        )
    return recommendations


def _candidate_summary(candidate: ProductCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "source": candidate.source,
        "source_type": candidate.source_type,
        "source_url": candidate.source_url,
        "scan_run_id": candidate.scan_run_id,
        "merchant_name": candidate.merchant_name,
        "brand_name": candidate.brand_name,
        "title": candidate.title,
        "description": candidate.description,
        "price_amount": (
            str(candidate.price_amount)
            if candidate.price_amount is not None
            else None
        ),
        "currency": candidate.currency,
        "merchant_url": candidate.merchant_url,
        "image_url": candidate.image_url,
        "availability": candidate.availability,
        "normalized_category": candidate.normalized_category,
        "city_scan_mode": candidate.city_scan_mode,
        "target_city_slug": candidate.target_city_slug,
        "recommended_city_slug": candidate.recommended_city_slug,
        "recommended_city_score": candidate.recommended_city_score,
        "city_assignment_status": candidate.city_assignment_status,
        "city_candidates": candidate.city_candidates or [],
        "merchant_verification": candidate.merchant_verification,
        "eligibility_status": candidate.eligibility_status,
        "eligibility_reasons": candidate.eligibility_reasons or [],
        "scoring_mode": candidate.scoring_mode,
        "scoring_version": candidate.scoring_version,
        "review_status": candidate.review_status,
    }


def import_single_product_candidate(
    db: Session,
    *,
    url: str,
    city_mode: CityScanMode | str,
    target_city_slug: str | None,
    category_override: str | None,
    active_city_slugs: tuple[str, ...],
    scan_run_id: str,
    concept_overrides: tuple[dict[str, Any], ...] = (),
    scoring_mode: str = "legacy",
) -> dict[str, Any]:
    mode = normalize_city_scan_mode(city_mode)
    if not active_city_slugs:
        raise ValueError(
            "Single-product analysis requires at least one active Haroona city."
        )

    page = fetch_single_product_page(url)
    merchant_name = merchant_name_from_url(page.canonical_url)
    merchant_guidance = get_merchant_source_guidance(
        page.canonical_url,
        merchant_name,
    )
    product = dict(page.product)
    product["id"] = _stable_external_product_id(page.canonical_url)
    product["_merchant_url"] = page.canonical_url
    raw_images = product.get("images")
    if isinstance(raw_images, list):
        product["images"] = [
            image
            for image in raw_images
            if isinstance(image, dict)
            and _safe_embedded_asset_url(
                str(image.get("src") or image.get("url") or "")
            )
        ]

    options = CollectionScanOptions(
        source_url=page.canonical_url,
        merchant_name=merchant_guidance.resolved_name,
        target_city_slug=target_city_slug,
        city_mode=mode.value,
        active_city_slugs=active_city_slugs,
        normalized_category=category_override,
        source="single_product",
        source_type="single_product",
        limit=1,
        image_mode="fast",
        scan_run_id=scan_run_id,
        merchant_verification=merchant_guidance.verification,
        merchant_profile_allowed=merchant_guidance.verification == "verified",
        concept_overrides=concept_overrides,
        scoring_mode=scoring_mode,
        score_all_active_cities=True,
        force_strict_distinctiveness=True,
        category_override=bool(category_override),
        preserve_unknown_availability=True,
    )
    built = build_candidate_payload_from_product(
        product,
        options=options,
        source_url=page.canonical_url,
        verify_image=False,
    )
    candidate_payload = built.payload
    counts = upsert_product_candidates(db, [candidate_payload])
    candidate = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.source == candidate_payload.source)
        .filter(
            ProductCandidate.external_product_id
            == candidate_payload.external_product_id
        )
        .one()
    )

    warnings: list[str] = []
    if candidate.eligibility_status != "eligible":
        reasons = ", ".join(
            reason.replace("_", " ")
            for reason in candidate.eligibility_reasons
        )
        warnings.append(
            "The product was added to the review queue"
            + (f" with eligibility notes: {reasons}." if reasons else ".")
        )

    summary = build_scan_summary(
        requested_limit=1,
        discovered_count=1,
        selected_count=1,
        created_count=counts["created"],
        updated_count=counts["updated"],
        skipped_duplicates=counts["skipped_duplicates"],
        image_mode="fast",
        pages_scanned=1,
        source_truncated=False,
        image_candidates_checked=built.image_candidates_checked,
        discovery_method=page.discovery_method,
        fallback_used=len(page.attempts) > 1,
        discovery_attempts=page.attempts,
    )
    summary["message"] = (
        "Single product analyzed and added to the review queue"
        if counts["created"]
        else "Existing product refreshed and kept in its current review state"
    ) + "."

    return {
        "status": "ok",
        "source_type": "single_product",
        "source_url": page.canonical_url,
        "scan_run_id": scan_run_id,
        "product_page": True,
        "product_page_detection": {
            "is_product_page": True,
            "method": page.discovery_method,
        },
        "merchant_name": candidate.merchant_name,
        "city_mode": mode.value,
        "target_city_slug": target_city_slug,
        "category_override": category_override,
        "scoring_mode": candidate.scoring_mode,
        "scoring_version": candidate.scoring_version,
        "found": 1,
        **counts,
        "candidate_id": candidate.id,
        "candidate": _candidate_summary(candidate),
        "recommendations": _recommendations(candidate.city_candidates or []),
        "summary": summary,
        "warnings": warnings,
        "items": [
            {
                "external_product_id": candidate.external_product_id,
                "title": candidate.title,
            }
        ],
    }

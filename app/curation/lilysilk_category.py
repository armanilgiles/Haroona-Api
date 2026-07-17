from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.eligibility import (
    add_reason_counts,
    blocking_reasons_only,
    evaluate_candidate_eligibility,
)
from app.curation.platform_alignment import score_platform_alignment
from app.curation.scoring import HYBRID_SCORING_VERSION, score_city_fit
from app.curation.shopify_collection import (
    USER_AGENT,
    CandidatePayload,
    CollectionScanOptions,
    _normalize_category,
    build_scan_summary,
    candidate_review_rank,
    upsert_product_candidates,
)
from app.curation.shopify_image_selection import (
    ShopifyImageCandidate,
    ShopifyImageSelectionCache,
    normalize_image_mode,
    select_shopify_product_image,
)


LILYSILK_API_ORIGIN = "https://lilydata.lilysilk.com"
LILYSILK_IMAGE_PREFIX = (
    "https://img.lilysilk.com/cdn-cgi/image/width=600,quality=90"
    "/media/catalog/product"
)
LILYSILK_PAGE_SIZE = 250
MAX_LILYSILK_SOURCE_PRODUCTS = 500

_CATEGORY_PATH_PATTERN = re.compile(
    r"^/(?P<store_code>[a-z]{2})/category/[^/]+\.html/?$",
    re.IGNORECASE,
)
_CATEGORY_ID_PATTERNS = (
    re.compile(
        r'\\"categoryId\\":(?P<category_id>\d+),'
        r'\\"lilysilkCategoryId\\":\d+',
    ),
    re.compile(
        r'"categoryId":(?P<category_id>\d+),'
        r'"lilysilkCategoryId":\d+',
    ),
)


@dataclass(frozen=True)
class LilySilkFetchResult:
    products: list[dict[str, Any]]
    pages_scanned: int
    source_truncated: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LilySilkCandidateDraft:
    payload: CandidatePayload
    image_candidates: list[ShopifyImageCandidate]
    product_type: str | None
    tags: list[str]


@dataclass(frozen=True)
class LilySilkBuildResult:
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


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_json_ld = False
        self._chunks: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "script":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if attr_map.get("type", "").lower() == "application/ld+json":
            self._inside_json_ld = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._inside_json_ld:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._inside_json_ld:
            return
        self._inside_json_ld = False
        raw = "".join(self._chunks).strip()
        if not raw:
            return
        try:
            self.documents.append(json.loads(raw))
        except json.JSONDecodeError:
            return


def _clean_source_url(source_url: str) -> str:
    parsed = urlparse(source_url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _store_code_from_url(source_url: str) -> str:
    parsed = urlparse(source_url.strip())
    match = _CATEGORY_PATH_PATTERN.match(parsed.path)
    if not match:
        raise ValueError(
            "LILYSILK URL must look like "
            "https://www.lilysilk.com/us/category/{slug}.html"
        )
    return match.group("store_code").lower()


def _category_id_from_html(html: str) -> int | None:
    for pattern in _CATEGORY_ID_PATTERNS:
        match = pattern.search(html)
        if match:
            return int(match.group("category_id"))
    return None


def _json_ld_products(html: str) -> list[dict[str, Any]]:
    parser = _JsonLdParser()
    parser.feed(html)
    products: list[dict[str, Any]] = []

    for document in parser.documents:
        documents = document if isinstance(document, list) else [document]
        for item in documents:
            if not isinstance(item, dict) or item.get("@type") != "ItemList":
                continue
            elements = item.get("itemListElement")
            if not isinstance(elements, list):
                continue
            for element in elements:
                product = element.get("item") if isinstance(element, dict) else None
                if not isinstance(product, dict) or product.get("@type") != "Product":
                    continue
                offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
                brand = product.get("brand") if isinstance(product.get("brand"), dict) else {}
                images = product.get("image")
                if not isinstance(images, list):
                    images = [images] if images else []
                products.append(
                    {
                        "title": product.get("name"),
                        "spu": product.get("sku"),
                        "url": product.get("url") or offers.get("url"),
                        "description": product.get("description"),
                        "brand_name": brand.get("name"),
                        "schema_price": offers.get("price"),
                        "schema_currency": offers.get("priceCurrency"),
                        "schema_availability": offers.get("availability"),
                        "spuImg": [
                            {
                                "url": image,
                                "isMain": index == 0,
                                "index": index + 1,
                            }
                            for index, image in enumerate(images)
                            if isinstance(image, str)
                        ],
                    }
                )

    return products


def _request_headers(source_url: str) -> dict[str, str]:
    parsed = urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": source_url,
    }


def _api_url(store_code: str) -> str:
    return (
        f"{LILYSILK_API_ORIGIN}/{store_code}"
        "/item/api/v3/categroy/queryProductList.json"
    )


def _fetch_lilysilk_category_result(
    options: CollectionScanOptions,
) -> LilySilkFetchResult:
    source_url = _clean_source_url(options.source_url)
    store_code = _store_code_from_url(source_url)
    headers = _request_headers(source_url)

    page_response = requests.get(
        source_url,
        headers=headers,
        timeout=options.request_timeout_seconds,
    )
    page_response.raise_for_status()
    page_html = page_response.text
    category_id = _category_id_from_html(page_html)
    fallback_products = _json_ld_products(page_html)

    if category_id is None:
        if fallback_products:
            return LilySilkFetchResult(
                products=fallback_products,
                pages_scanned=1,
                source_truncated=True,
                warnings=(
                    "LILYSILK category pagination was unavailable; only the products "
                    "embedded in the page were scanned.",
                ),
            )
        raise RuntimeError("Could not find the LILYSILK category identifier in the page")

    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []
    pages_scanned = 0
    source_products_seen = 0
    total_count: int | None = None
    max_pages = 10

    for page in range(1, max_pages + 1):
        payload = {
            "pageSize": LILYSILK_PAGE_SIZE,
            "categoryId": category_id,
            "orderBy": 0,
            "occasion": [],
            "page": page,
            "pageType": 1,
            "clickItemsIds": [],
            "filterItems": [],
        }
        try:
            response = requests.post(
                _api_url(store_code),
                json=payload,
                headers=headers,
                timeout=options.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            page_products = data.get("productList") if isinstance(data, dict) else None
            if body.get("success") is not True or not isinstance(page_products, list):
                raise ValueError("LILYSILK response did not contain a product list")
        except Exception as exc:  # noqa: BLE001 - preserve useful partial results
            if not products and fallback_products:
                return LilySilkFetchResult(
                    products=fallback_products,
                    pages_scanned=1,
                    source_truncated=True,
                    warnings=(
                        f"LILYSILK product API was unavailable ({exc}); only the "
                        "products embedded in the page were scanned.",
                    ),
                )
            if not products:
                raise RuntimeError(f"Could not fetch LILYSILK category products: {exc}") from exc
            warnings.append(
                f"LILYSILK pagination stopped after page {pages_scanned}: {exc}."
            )
            break

        pages_scanned += 1
        page_meta = body.get("page") if isinstance(body.get("page"), dict) else {}
        try:
            total_count = int(page_meta.get("total"))
        except (TypeError, ValueError):
            total_count = None

        for product in page_products:
            if not isinstance(product, dict):
                continue
            if source_products_seen >= MAX_LILYSILK_SOURCE_PRODUCTS:
                break
            source_products_seen += 1
            product_id = str(
                product.get("spu") or product.get("id") or product.get("url") or ""
            ).strip()
            if not product_id or product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            products.append(product)

        if source_products_seen >= MAX_LILYSILK_SOURCE_PRODUCTS:
            break
        if total_count is not None and source_products_seen >= total_count:
            break
        if not page_products or (
            total_count is None and len(page_products) < LILYSILK_PAGE_SIZE
        ):
            break

    source_truncated = bool(
        (total_count is not None and total_count > source_products_seen)
        or (total_count is None and source_products_seen >= MAX_LILYSILK_SOURCE_PRODUCTS)
        or warnings
    )
    if total_count is not None and total_count > MAX_LILYSILK_SOURCE_PRODUCTS:
        warnings.append(
            f"The source scan stopped at {MAX_LILYSILK_SOURCE_PRODUCTS} products; "
            "narrow the category if you need to inspect later products."
        )

    return LilySilkFetchResult(
        products=products,
        pages_scanned=pages_scanned,
        source_truncated=source_truncated,
        warnings=tuple(warnings),
    )


def fetch_lilysilk_category_products(
    options: CollectionScanOptions,
) -> list[dict[str, Any]]:
    return _fetch_lilysilk_category_result(options).products


def _price_from_product(product: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    raw_price = product.get("discountMinPrice")
    if isinstance(raw_price, dict):
        try:
            precision = int(raw_price.get("precision") or 2)
            divisor = Decimal(10) ** precision
            price = (Decimal(str(raw_price.get("cent"))) / divisor).quantize(
                Decimal("0.01")
            )
            return price, str(raw_price.get("currency") or "").strip() or None
        except (InvalidOperation, TypeError, ValueError):
            pass

    try:
        schema_price = product.get("schema_price")
        if schema_price is not None:
            return Decimal(str(schema_price)).quantize(Decimal("0.01")), (
                str(product.get("schema_currency") or "").strip() or None
            )
    except (InvalidOperation, TypeError, ValueError):
        pass

    return None, None


def _product_url(product: dict[str, Any], source_url: str, store_code: str) -> str | None:
    raw_url = str(product.get("url") or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return _clean_source_url(raw_url)
    slug = raw_url.strip("/")
    if slug.endswith(".html"):
        slug = slug[:-5]
    source = urlparse(source_url)
    return f"{source.scheme}://{source.netloc}/{store_code}/product/{slug}.html"


def _image_url(raw_url: str) -> str | None:
    cleaned = raw_url.strip().replace("&amp;", "&")
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned
    if parsed.path.startswith("/"):
        return f"{LILYSILK_IMAGE_PREFIX}{parsed.path}"
    return None


def _image_candidates(
    product: dict[str, Any],
    title: str,
) -> list[ShopifyImageCandidate]:
    images = product.get("spuImg")
    if not isinstance(images, list):
        return []
    candidates: list[ShopifyImageCandidate] = []
    seen: set[str] = set()

    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        if image.get("mediaType") not in {None, 1, "1"}:
            continue
        url = _image_url(str(image.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            position = int(image.get("index") or index + 1)
        except (TypeError, ValueError):
            position = index + 1
        candidates.append(
            ShopifyImageCandidate(
                url=url,
                alt=str(image.get("alt") or title).strip() or None,
                width=600,
                height=750,
                position=position,
            )
        )

    return candidates[:8]


def _product_type_and_tags(product: dict[str, Any]) -> tuple[str | None, list[str]]:
    ga_attribute = product.get("gaAttribute")
    category_ga = product.get("categoryGa")
    product_type = None
    tags: list[str] = []

    if isinstance(ga_attribute, dict):
        product_type = str(ga_attribute.get("pcat") or "").strip() or None
    if isinstance(category_ga, dict):
        for value in category_ga.values():
            if isinstance(value, list):
                tags.extend(str(item) for item in value if item)
    default_color = str(product.get("defaultColor") or "").strip()
    if default_color:
        tags.append(default_color)

    return product_type, tags


def _build_candidate_draft(
    product: dict[str, Any],
    *,
    options: CollectionScanOptions,
    source_url: str,
    store_code: str,
) -> LilySilkCandidateDraft | None:
    title = str(product.get("title") or "").strip()
    external_id = str(
        product.get("spu") or product.get("id") or product.get("url") or ""
    ).strip()
    if not title or not external_id:
        return None

    product_type, tags = _product_type_and_tags(product)
    normalized_category = _normalize_category(
        title,
        product_type,
        options.normalized_category,
    )
    description = str(product.get("description") or "").strip() or None
    brand_name = str(product.get("brand_name") or "").strip() or options.merchant_name
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
    )
    price_amount, currency = _price_from_product(product)
    schema_availability = str(product.get("schema_availability") or "").lower()
    availability = (
        "in_stock"
        if product.get("status") == 2 or schema_availability.endswith("instock")
        else "unknown"
    )

    merchant_url = _product_url(product, source_url, store_code)
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

    image_candidates = _image_candidates(product, title)
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

    return LilySilkCandidateDraft(
        payload=CandidatePayload(
            source=options.source,
            source_type=options.source_type,
            source_url=source_url,
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


def build_lilysilk_candidate_payload_result(
    options: CollectionScanOptions,
) -> LilySilkBuildResult:
    fetch_result = _fetch_lilysilk_category_result(options)
    source_url = _clean_source_url(options.source_url)
    store_code = _store_code_from_url(source_url)
    drafts: list[LilySilkCandidateDraft] = []
    skipped_invalid_products = 0
    skipped_ineligible_products = 0
    ineligible_reason_counts: dict[str, int] = {}

    for product in fetch_result.products:
        draft = _build_candidate_draft(
            product,
            options=options,
            source_url=source_url,
            store_code=store_code,
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
    image_mode = normalize_image_mode(options.image_mode)

    for draft in drafts:
        if len(payloads) >= options.limit:
            break
        selection = select_shopify_product_image(
            draft.image_candidates,
            image_mode=image_mode,
            referer=source_url,
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
    return LilySilkBuildResult(
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
    )


def build_lilysilk_candidate_payloads(
    options: CollectionScanOptions,
) -> list[CandidatePayload]:
    return build_lilysilk_candidate_payload_result(options).payloads


def scan_and_save_lilysilk_category(
    db: Session,
    options: CollectionScanOptions,
) -> dict[str, Any]:
    build_result = build_lilysilk_candidate_payload_result(options)
    payloads = build_result.payloads
    counts = upsert_product_candidates(db, payloads)
    image_mode = normalize_image_mode(options.image_mode)
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
        image_mode=image_mode,
        pages_scanned=build_result.pages_scanned,
        source_truncated=build_result.source_truncated,
        image_candidates_checked=build_result.image_candidates_checked,
    )
    return {
        "status": "ok",
        "source_url": _clean_source_url(options.source_url),
        "scan_run_id": options.scan_run_id,
        "merchant_name": options.merchant_name,
        "target_city_slug": options.target_city_slug,
        "image_mode": image_mode,
        "found": len(payloads),
        **counts,
        "summary": summary,
        "warnings": list(build_result.warnings),
        "items": [
            {
                "external_product_id": item.external_product_id,
                "title": item.title,
                "price_amount": (
                    str(item.price_amount) if item.price_amount is not None else None
                ),
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
            for item in payloads
        ],
    }

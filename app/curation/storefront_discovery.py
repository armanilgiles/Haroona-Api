from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests


MAX_EMBEDDED_JSON_BYTES = 5_000_000
MAX_STOREFRONT_PRODUCT_PAGES = 100
_PRODUCT_PATH_PATTERN = re.compile(
    r"/(?:products?|p|item)/[^/?#]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiscoveryAttempt:
    method: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "method": self.method,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StorefrontPageExtraction:
    products: list[dict[str, Any]]
    product_links: list[str]


@dataclass(frozen=True)
class StorefrontDiscoveryResult:
    products: list[dict[str, Any]]
    discovery_method: str
    pages_scanned: int
    source_truncated: bool
    attempts: tuple[DiscoveryAttempt, ...]
    warnings: tuple[str, ...] = ()


class StorefrontDiscoveryError(RuntimeError):
    def __init__(self, message: str, *, attempts: list[DiscoveryAttempt]) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


class _StorefrontHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self._script_type: str | None = None
        self._script_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        normalized_tag = tag.lower()
        if normalized_tag == "script":
            script_type = attr_map.get("type", "").lower()
            if script_type in {"application/json", "application/ld+json"}:
                self._script_type = script_type
                self._script_chunks = []
            return
        if normalized_tag == "a" and attr_map.get("href"):
            self.links.append(attr_map["href"])
            return
        if normalized_tag == "meta" and attr_map.get("content"):
            key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            if key:
                self.meta.setdefault(key, attr_map["content"])

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._script_type is None:
            return
        raw = "".join(self._script_chunks).strip()
        if raw and len(raw.encode("utf-8")) <= MAX_EMBEDDED_JSON_BYTES:
            self.scripts.append((self._script_type, raw))
        self._script_type = None
        self._script_chunks = []


def _clean_url(value: str, *, base_url: str) -> str | None:
    cleaned = unescape(str(value or "")).strip()
    if not cleaned or cleaned.startswith(("javascript:", "mailto:", "tel:")):
        return None
    absolute = urljoin(base_url, cleaned)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _same_store_url(value: str, *, base_url: str) -> str | None:
    cleaned = _clean_url(value, base_url=base_url)
    if not cleaned:
        return None
    base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    candidate_host = (urlparse(cleaned).hostname or "").lower().removeprefix("www.")
    if candidate_host != base_host:
        return None
    return cleaned


def _product_handle(product_url: str | None, fallback: Any = None) -> str:
    if product_url:
        parts = [part for part in urlparse(product_url).path.split("/") if part]
        if parts:
            return parts[-1].removesuffix(".html").removesuffix(".js")
    return re.sub(r"[^a-z0-9]+", "-", str(fallback or "").lower()).strip("-")


def _brand_name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image_rows(value: Any, *, base_url: str) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else [value]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, dict):
            raw_url = item.get("src") or item.get("url") or item.get("image_url")
            alt = item.get("alt") or item.get("altText")
        else:
            raw_url = item
            alt = None
        if not isinstance(raw_url, str):
            continue
        image_url = _clean_url(raw_url, base_url=base_url)
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        row = {"src": image_url}
        if isinstance(alt, str) and alt.strip():
            row["alt"] = alt.strip()
        rows.append(row)
    return rows


def _availability(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").lower()
    if "instock" in normalized or "in_stock" in normalized or normalized == "available":
        return True
    if "outofstock" in normalized or "out_of_stock" in normalized or normalized == "soldout":
        return False
    return None


def _variant_rows(
    product: dict[str, Any],
    *,
    assume_shopify_cents: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    raw_variants = product.get("variants")
    currency = product.get("currency") or product.get("priceCurrency")
    if not isinstance(raw_variants, list):
        raw_offers = product.get("offers")
        raw_variants = raw_offers if isinstance(raw_offers, list) else [raw_offers]

    variants: list[dict[str, Any]] = []
    for raw in raw_variants:
        if not isinstance(raw, dict):
            continue
        raw_price = (
            raw.get("price")
            or raw.get("lowPrice")
            or raw.get("highPrice")
            or product.get("price")
        )
        if assume_shopify_cents and isinstance(raw_price, int):
            raw_price = f"{raw_price / 100:.2f}"
        available = _availability(raw.get("available"))
        if available is None:
            available = _availability(raw.get("availability"))
        variants.append(
            {
                "id": raw.get("id") or raw.get("sku"),
                "price": raw_price,
                "available": available is not False,
            }
        )
        currency = currency or raw.get("priceCurrency") or raw.get("currency")

    if not variants and product.get("price") is not None:
        raw_price = product.get("price")
        if assume_shopify_cents and isinstance(raw_price, int):
            raw_price = f"{raw_price / 100:.2f}"
        variants.append(
            {
                "price": raw_price,
                "available": _availability(product.get("availability")) is not False,
            }
        )
    return variants, str(currency).upper() if currency else None


def product_from_mapping(
    product: dict[str, Any],
    *,
    base_url: str,
    assume_shopify_cents: bool = False,
) -> dict[str, Any] | None:
    title = product.get("title") or product.get("name")
    if not isinstance(title, str) or not title.strip():
        return None

    raw_url = (
        product.get("url")
        or product.get("productUrl")
        or product.get("product_url")
        or product.get("merchant_url")
    )
    product_url = _clean_url(raw_url, base_url=base_url) if raw_url else None
    handle = str(product.get("handle") or "").strip() or _product_handle(
        product_url,
        fallback=title,
    )
    external_id = str(
        product.get("id")
        or product.get("productId")
        or product.get("product_id")
        or product.get("sku")
        or product_url
        or handle
    ).strip()
    if not handle or not external_id:
        return None

    image_value = (
        product.get("images")
        or product.get("image")
        or product.get("featured_image")
        or product.get("featuredImage")
    )
    variants, currency = _variant_rows(
        product,
        assume_shopify_cents=assume_shopify_cents,
    )
    description = product.get("body_html") or product.get("description")
    tags = product.get("tags")
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]

    return {
        "id": external_id,
        "title": title.strip(),
        "handle": handle,
        "vendor": _brand_name(product.get("vendor") or product.get("brand")),
        "product_type": product.get("product_type") or product.get("category"),
        "body_html": description,
        "tags": tags if isinstance(tags, list) else [],
        "variants": variants,
        "images": _image_rows(image_value, base_url=base_url),
        "_merchant_url": product_url,
        "_currency": currency,
    }


def _looks_like_product(value: dict[str, Any]) -> bool:
    schema_type = value.get("@type")
    if isinstance(schema_type, list):
        schema_types = {str(item).lower() for item in schema_type}
    else:
        schema_types = {str(schema_type or "").lower()}
    if "product" in schema_types:
        return True
    if not (value.get("title") or value.get("name")):
        return False
    return any(
        key in value
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


def _products_from_document(
    document: Any,
    *,
    base_url: str,
) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        if _looks_like_product(value):
            product = product_from_mapping(value, base_url=base_url)
            if product:
                products.append(product)

        for key, nested in value.items():
            if key in {"brand", "offers", "variants", "images", "image"}:
                continue
            visit(nested)

    visit(document)
    return products


def _dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    def richness(product: dict[str, Any]) -> int:
        return sum(
            1
            for key in ("title", "vendor", "body_html", "variants", "images", "_merchant_url")
            if product.get(key)
        )

    for product in products:
        key = str(
            product.get("_merchant_url")
            or product.get("id")
            or product.get("handle")
            or ""
        ).strip()
        if not key:
            continue
        current = by_key.get(key)
        if current is None or richness(product) > richness(current):
            by_key[key] = product
    return list(by_key.values())


def _product_is_complete(product: dict[str, Any]) -> bool:
    return bool(
        product.get("title")
        and product.get("handle")
        and product.get("variants")
        and product.get("images")
    )


def extract_storefront_page(html: str, *, base_url: str) -> StorefrontPageExtraction:
    parser = _StorefrontHtmlParser()
    parser.feed(html)
    products: list[dict[str, Any]] = []
    links: list[str] = []

    for _, raw in parser.scripts:
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        products.extend(_products_from_document(document, base_url=base_url))

    for product in products:
        merchant_url = product.get("_merchant_url")
        if merchant_url:
            same_store = _same_store_url(str(merchant_url), base_url=base_url)
            if same_store:
                links.append(same_store)

    for raw_link in parser.links:
        candidate = _same_store_url(raw_link, base_url=base_url)
        if candidate and _PRODUCT_PATH_PATTERN.search(urlparse(candidate).path):
            links.append(candidate)

    deduped_links = list(dict.fromkeys(links))
    return StorefrontPageExtraction(
        products=_dedupe_products(products),
        product_links=deduped_links,
    )


def _product_from_meta(html: str, *, product_url: str) -> dict[str, Any] | None:
    parser = _StorefrontHtmlParser()
    parser.feed(html)
    meta = parser.meta
    title = meta.get("og:title") or meta.get("twitter:title")
    if not title:
        return None
    return product_from_mapping(
        {
            "title": title,
            "url": meta.get("og:url") or product_url,
            "description": meta.get("og:description") or meta.get("description"),
            "image": meta.get("og:image") or meta.get("twitter:image"),
            "price": meta.get("product:price:amount"),
            "priceCurrency": meta.get("product:price:currency"),
            "availability": meta.get("product:availability"),
            "brand": meta.get("product:brand"),
        },
        base_url=product_url,
    )


def _fetch_product(
    product_url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: int,
) -> tuple[dict[str, Any] | None, int]:
    pages_scanned = 0
    if "/products/" in urlparse(product_url).path:
        json_url = f"{product_url.rstrip('/')}.js"
        try:
            response = requests.get(json_url, headers=headers, timeout=timeout_seconds)
            pages_scanned += 1
            if response.status_code < 400:
                payload = response.json()
                if isinstance(payload, dict):
                    product = product_from_mapping(
                        payload,
                        base_url=product_url,
                        assume_shopify_cents=True,
                    )
                    if product and _product_is_complete(product):
                        product["_merchant_url"] = product_url
                        return product, pages_scanned
        except Exception:  # noqa: BLE001 - the public HTML page is the next fallback
            pass

    try:
        response = requests.get(product_url, headers=headers, timeout=timeout_seconds)
        pages_scanned += 1
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - caller reports aggregate crawl coverage
        return None, pages_scanned

    extraction = extract_storefront_page(response.text, base_url=product_url)
    for product in extraction.products:
        product["_merchant_url"] = product.get("_merchant_url") or product_url
        if _product_is_complete(product):
            return product, pages_scanned
    meta_product = _product_from_meta(response.text, product_url=product_url)
    if meta_product:
        meta_product["_merchant_url"] = product_url
    return meta_product, pages_scanned


def discover_storefront_products(
    source_url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: int,
    max_products: int,
) -> StorefrontDiscoveryResult:
    attempts: list[DiscoveryAttempt] = []
    try:
        response = requests.get(source_url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - wrap with an actionable discovery error
        attempts.append(
            DiscoveryAttempt(
                method="public_storefront_html",
                status="failed",
                detail=f"The public collection page could not be fetched: {exc}",
            )
        )
        raise StorefrontDiscoveryError(
            attempts[-1].detail,
            attempts=attempts,
        ) from exc

    extraction = extract_storefront_page(response.text, base_url=source_url)
    attempts.append(
        DiscoveryAttempt(
            method="public_storefront_html",
            status="succeeded",
            detail="The public collection page was fetched.",
        )
    )
    embedded = [product for product in extraction.products if _product_is_complete(product)]
    attempts.append(
        DiscoveryAttempt(
            method="embedded_storefront_data",
            status="succeeded" if embedded else "no_data",
            detail=(
                f"Found {len(embedded)} complete product record(s) in embedded structured data."
                if embedded
                else "No complete product records were present in embedded structured data."
            ),
        )
    )

    links = extraction.product_links
    attempts.append(
        DiscoveryAttempt(
            method="collection_product_links",
            status="succeeded" if links else "no_data",
            detail=(
                f"Found {len(links)} unique public product link(s)."
                if links
                else "No recognizable public product links were found."
            ),
        )
    )

    products = list(embedded)
    existing_urls = {
        str(product.get("_merchant_url"))
        for product in products
        if product.get("_merchant_url")
    }
    crawl_links = [link for link in links if link not in existing_urls]
    page_limit = min(
        max(max_products, 1),
        MAX_STOREFRONT_PRODUCT_PAGES,
    )
    source_truncated = len(crawl_links) > page_limit
    successful_crawls = 0
    pages_scanned = 1
    for product_url in crawl_links[:page_limit]:
        product, request_count = _fetch_product(
            product_url,
            headers=headers,
            timeout_seconds=min(timeout_seconds, 10),
        )
        pages_scanned += request_count
        if product:
            successful_crawls += 1
            products.append(product)

    if crawl_links:
        attempts.append(
            DiscoveryAttempt(
                method="product_page_crawl",
                status="succeeded" if successful_crawls else "failed",
                detail=(
                    f"Parsed {successful_crawls} of {min(len(crawl_links), page_limit)} "
                    "attempted product page(s)."
                ),
            )
        )

    products = _dedupe_products(products)
    warnings: list[str] = []
    if source_truncated:
        warnings.append(
            f"The storefront fallback capped product-page inspection at {page_limit}; "
            "narrow the collection to inspect later products."
        )
    if not products:
        attempts_text = "; ".join(attempt.detail for attempt in attempts)
        raise StorefrontDiscoveryError(
            "The public storefront did not expose usable product data. " + attempts_text,
            attempts=attempts,
        )

    method = "product_page_crawl" if successful_crawls else "embedded_storefront_data"
    return StorefrontDiscoveryResult(
        products=products,
        discovery_method=method,
        pages_scanned=pages_scanned,
        source_truncated=source_truncated,
        attempts=tuple(attempts),
        warnings=tuple(warnings),
    )

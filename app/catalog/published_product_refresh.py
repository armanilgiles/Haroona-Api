from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.single_product import (
    MAX_PRODUCT_PAGE_BYTES,
    MAX_REDIRECTS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    _assert_public_host,
)
from app.curation.storefront_discovery import (
    extract_product_from_meta,
    extract_storefront_page,
    product_from_mapping,
)
from app.models import Brand, Product, ProductPriceSnapshot


class RefreshStatus(str, Enum):
    UNCHANGED = "unchanged"
    PRICE_CHANGED = "price_changed"
    AVAILABLE = "available"
    LIKELY_UNAVAILABLE = "likely_unavailable"
    PRODUCT_UNAVAILABLE = "product_unavailable"
    AFFILIATE_LINK_BROKEN = "affiliate_link_broken"
    BLOCKED_OR_UNKNOWN = "blocked_or_unknown"
    TEMPORARY_FAILURE = "temporary_failure"
    PARSE_FAILURE = "parse_failure"


SUCCESS_STATUSES = {
    RefreshStatus.UNCHANGED,
    RefreshStatus.PRICE_CHANGED,
    RefreshStatus.AVAILABLE,
}
REVIEW_STATUSES = {
    RefreshStatus.LIKELY_UNAVAILABLE,
    RefreshStatus.PRODUCT_UNAVAILABLE,
    RefreshStatus.AFFILIATE_LINK_BROKEN,
    RefreshStatus.PARSE_FAILURE,
}
TRACKING_QUERY_NAMES = {
    "_ga",
    "_gl",
    "aff",
    "affiliate",
    "affid",
    "aff_id",
    "cjdata",
    "cjevent",
    "fbclid",
    "gclid",
    "irclickid",
    "irgwc",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
}
BOT_MARKERS = (
    "access denied",
    "are you a human",
    "captcha",
    "cf-chl-",
    "cloudflare ray id",
    "enable javascript and cookies to continue",
    "robot verification",
    "verify you are human",
)
UNAVAILABLE_MARKERS = (
    "page not found",
    "product has been removed",
    "product not found",
    "this item is no longer available",
    "this product is no longer available",
)
COLLECTION_PATH_PATTERN = re.compile(
    r"/(?:collections?|categories?|catalog|search)(?:/|$)",
    re.IGNORECASE,
)
PRODUCT_PATH_PATTERN = re.compile(
    r"/(?:products?|product-detail|productdetails?|p|item|goods?|pd)/[^/?#]+",
    re.IGNORECASE,
)


def clean_stored_url(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    while cleaned.endswith("|"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned or None


def normalize_product_url(value: str | None) -> str | None:
    """Return a comparison key without mutating the stored URL."""
    cleaned = clean_stored_url(value)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".").removeprefix("www.")
    try:
        port = parsed.port
    except ValueError:
        return None
    if port and port not in {80, 443}:
        host = f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_NAMES
    ]
    return urlunparse(("", host, path, "", urlencode(sorted(query)), ""))


def urls_match_product_identity(left: str | None, right: str | None) -> bool:
    left_key = normalize_product_url(left)
    right_key = normalize_product_url(right)
    return bool(left_key and right_key and left_key == right_key)


def _decimal_price(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        amount = value
    else:
        cleaned = re.sub(r"[^0-9,.\-]", "", str(value)).strip()
        if not cleaned:
            return None
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return None
    if amount < 0 or amount > Decimal("10000000"):
        return None
    return amount


def _money(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _title_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 1
        and token
        not in {"and", "at", "buy", "for", "from", "online", "shop", "the"}
    }


def _title_similarity(left: str | None, right: str | None) -> float:
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _is_homepage_url(value: str | None) -> bool:
    if not value:
        return False
    path = urlparse(value).path.rstrip("/").lower()
    return path in {"", "/en", "/en-gb", "/en-us", "/uk", "/us"}


def _is_collection_url(value: str | None) -> bool:
    return bool(value and COLLECTION_PATH_PATTERN.search(urlparse(value).path))


def _looks_like_product_url(value: str | None) -> bool:
    return bool(value and PRODUCT_PATH_PATTERN.search(urlparse(value).path))


def _product_path_identifiers(value: str | None) -> set[str]:
    if not value:
        return set()
    path = urlparse(value).path.lower()
    identifiers = set(re.findall(r"(?<!\d)\d{6,}(?!\d)", path))
    final_segment = path.rstrip("/").rsplit("/", 1)[-1]
    final_token = re.split(r"[-_.]", final_segment)[-1]
    if len(final_token) >= 8:
        identifiers.add(final_token)
    return identifiers


def _availability(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").lower().replace("-", "").replace("_", "")
    if any(token in normalized for token in ("outofstock", "soldout", "unavailable")):
        return False
    if any(token in normalized for token in ("instock", "available")):
        return True
    return None


class _RefreshHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_url: str | None = None
        self.meta: dict[str, str] = {}
        self.json_scripts: list[str] = []
        self.page_title = ""
        self.visible_text: list[str] = []
        self._in_title = False
        self._script_is_json = False
        self._script_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        normalized = tag.lower()
        if normalized == "title":
            self._in_title = True
        elif normalized == "link":
            rel = attrs_map.get("rel", "").lower().split()
            if "canonical" in rel and attrs_map.get("href"):
                self.canonical_url = attrs_map["href"].strip()
        elif normalized == "meta" and attrs_map.get("content"):
            key = (attrs_map.get("property") or attrs_map.get("name") or "").lower()
            if key:
                self.meta.setdefault(key, attrs_map["content"].strip())
        elif normalized == "script":
            script_type = attrs_map.get("type", "").lower()
            self._script_is_json = script_type in {
                "application/json",
                "application/ld+json",
            }
            self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.page_title += data
        if self._script_is_json:
            self._script_chunks.append(data)
        elif data.strip() and len(self.visible_text) < 4000:
            self.visible_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self._in_title = False
        elif normalized == "script":
            if self._script_is_json:
                raw = "".join(self._script_chunks).strip()
                if raw and len(raw.encode("utf-8")) <= MAX_PRODUCT_PAGE_BYTES:
                    self.json_scripts.append(raw)
            self._script_is_json = False
            self._script_chunks = []


@dataclass(frozen=True)
class ParsedProduct:
    title: str | None = None
    current_price: Decimal | None = None
    regular_price: Decimal | None = None
    currency: str | None = None
    available: bool | None = None
    identifier: str | None = None
    canonical_url: str | None = None
    has_structured_product: bool = False
    page_title: str | None = None
    page_text: str = ""


@dataclass(frozen=True)
class PageInspection:
    status: RefreshStatus | None
    reason: str
    requested_url: str | None
    final_url: str | None = None
    parsed: ParsedProduct = ParsedProduct()
    confidence: str = "low"
    redirect_count: int = 0


@dataclass(frozen=True)
class ProductRefreshItem:
    product_id: int
    merchant: str
    stored_title: str
    stored_price: Decimal | None
    detected_price: Decimal | None
    stored_regular_price: Decimal | None
    detected_regular_price: Decimal | None
    currency: str
    detected_currency: str | None
    original_url: str | None
    affiliate_url: str | None
    final_url: str | None
    affiliate_final_url: str | None
    refresh_status: RefreshStatus
    affiliate_status: str
    confidence: str
    reason: str
    would_update: bool
    would_flag_for_review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "merchant": self.merchant,
            "stored_title": self.stored_title,
            "stored_price": _money(self.stored_price),
            "detected_price": _money(self.detected_price),
            "stored_regular_price": _money(self.stored_regular_price),
            "detected_regular_price": _money(self.detected_regular_price),
            "currency": self.currency,
            "detected_currency": self.detected_currency,
            "original_url": self.original_url,
            "affiliate_url": self.affiliate_url,
            "final_url": self.final_url,
            "affiliate_final_url": self.affiliate_final_url,
            "refresh_status": self.refresh_status.value,
            "affiliate_status": self.affiliate_status,
            "confidence": self.confidence,
            "reason": self.reason,
            "would_update": self.would_update,
            "would_flag_for_review": self.would_flag_for_review,
        }


@dataclass(frozen=True)
class ProductRefreshReport:
    mode: str
    generated_at: datetime
    results: tuple[ProductRefreshItem, ...]

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(item.refresh_status.value for item in self.results)
        return {
            "published_products_checked": len(self.results),
            **{
                status.value: counts.get(status.value, 0)
                for status in RefreshStatus
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "generated_at": self.generated_at.isoformat(),
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _iter_product_documents(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _iter_product_documents(item)
        return
    if not isinstance(value, dict):
        return
    wrapped = value.get("product")
    if isinstance(wrapped, dict):
        yield wrapped
    schema_type = value.get("@type")
    schema_types = (
        {str(item).lower() for item in schema_type}
        if isinstance(schema_type, list)
        else {str(schema_type or "").lower()}
    )
    if "product" in schema_types:
        yield value
    for key, nested in value.items():
        if key not in {"brand", "image", "images", "offers", "variants"}:
            yield from _iter_product_documents(nested)


def _prices_from_mapping(
    product: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, str | None, bool | None]:
    raw_offers = product.get("offers")
    offers = raw_offers if isinstance(raw_offers, list) else [raw_offers]
    current_prices: list[Decimal] = []
    regular_prices: list[Decimal] = []
    currency = product.get("priceCurrency") or product.get("currency")
    availability_values: list[bool] = []

    direct_current = _decimal_price(product.get("sale_price") or product.get("price"))
    direct_regular = _decimal_price(
        product.get("regular_price")
        or product.get("compare_at_price")
        or product.get("compareAtPrice")
    )
    if direct_current is not None:
        current_prices.append(direct_current)
    if direct_regular is not None:
        regular_prices.append(direct_regular)

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        offer_price = _decimal_price(
            offer.get("price")
            or offer.get("salePrice")
            or offer.get("lowPrice")
        )
        high_price = _decimal_price(offer.get("highPrice"))
        if offer_price is not None:
            current_prices.append(offer_price)
        if high_price is not None and (
            offer_price is None or high_price > offer_price
        ):
            regular_prices.append(high_price)
        currency = currency or offer.get("priceCurrency") or offer.get("currency")
        offer_availability = _availability(
            offer.get("availability")
            if "availability" in offer
            else offer.get("available")
        )
        if offer_availability is not None:
            availability_values.append(offer_availability)
        specifications = offer.get("priceSpecification")
        if not isinstance(specifications, list):
            specifications = [specifications]
        for specification in specifications:
            if not isinstance(specification, dict):
                continue
            amount = _decimal_price(specification.get("price"))
            price_type = str(
                specification.get("priceType")
                or specification.get("name")
                or ""
            ).lower()
            if amount is None:
                continue
            if any(token in price_type for token in ("list", "regular", "was")):
                regular_prices.append(amount)
            elif any(token in price_type for token in ("sale", "current")):
                current_prices.append(amount)
            currency = currency or specification.get("priceCurrency")

    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            amount = _decimal_price(variant.get("price"))
            compare_at = _decimal_price(
                variant.get("compare_at_price")
                or variant.get("compareAtPrice")
            )
            if amount is not None:
                current_prices.append(amount)
            if compare_at is not None and (amount is None or compare_at > amount):
                regular_prices.append(compare_at)
            variant_availability = _availability(
                variant.get("available")
                if "available" in variant
                else variant.get("availability")
            )
            if variant_availability is not None:
                availability_values.append(variant_availability)

    current = min(current_prices) if current_prices else None
    regular_candidates = [
        amount
        for amount in regular_prices
        if current is None or amount >= current
    ]
    regular = max(regular_candidates) if regular_candidates else None
    available = any(availability_values) if availability_values else _availability(
        product.get("availability")
    )
    return (
        current,
        regular,
        str(currency).upper()[:3] if currency else None,
        available,
    )


def _parsed_product_from_mapping(
    product: dict[str, Any],
    *,
    base_url: str,
) -> ParsedProduct | None:
    normalized = product_from_mapping(product, base_url=base_url)
    if not normalized:
        return None
    price, regular_price, currency, available = _prices_from_mapping(product)
    if price is None:
        variant_prices = [
            _decimal_price(variant.get("price"))
            for variant in normalized.get("variants") or []
            if isinstance(variant, dict)
        ]
        variant_prices = [amount for amount in variant_prices if amount is not None]
        price = min(variant_prices) if variant_prices else None
    currency = currency or normalized.get("_currency")
    identifier = (
        product.get("sku")
        or product.get("productID")
        or product.get("productId")
        or product.get("mpn")
        or product.get("gtin")
        or product.get("id")
        or product.get("handle")
    )
    return ParsedProduct(
        title=normalized.get("title"),
        current_price=price,
        regular_price=regular_price,
        currency=str(currency).upper()[:3] if currency else None,
        available=available,
        identifier=str(identifier) if identifier is not None else None,
        canonical_url=normalized.get("_merchant_url"),
        has_structured_product=True,
    )


def _merge_page_context(
    parsed: ParsedProduct,
    *,
    parser: _RefreshHtmlParser,
    final_url: str,
) -> ParsedProduct:
    canonical = (
        urljoin(final_url, parser.canonical_url)
        if parser.canonical_url
        else parsed.canonical_url
    )
    return ParsedProduct(
        title=parsed.title,
        current_price=parsed.current_price,
        regular_price=parsed.regular_price,
        currency=parsed.currency,
        available=parsed.available,
        identifier=parsed.identifier,
        canonical_url=canonical,
        has_structured_product=parsed.has_structured_product,
        page_title=re.sub(r"\s+", " ", parser.page_title).strip() or None,
        page_text=" ".join(parser.visible_text).lower(),
    )


def _extract_product(html: str, *, final_url: str) -> ParsedProduct:
    parser = _RefreshHtmlParser()
    parser.feed(html)
    candidates: list[ParsedProduct] = []
    for raw in parser.json_scripts:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for product_document in _iter_product_documents(document):
            parsed = _parsed_product_from_mapping(
                product_document,
                base_url=final_url,
            )
            if parsed:
                candidates.append(parsed)

    if not candidates:
        extraction = extract_storefront_page(html, base_url=final_url)
        exact = [
            product
            for product in extraction.products
            if urls_match_product_identity(
                str(product.get("_merchant_url") or ""),
                final_url,
            )
        ]
        products = exact or (
            extraction.products
            if len(extraction.products) == 1
            and _looks_like_product_url(final_url)
            else []
        )
        for product in products:
            price, regular, currency, available = _prices_from_mapping(product)
            candidates.append(
                ParsedProduct(
                    title=product.get("title"),
                    current_price=price,
                    regular_price=regular,
                    currency=currency or product.get("_currency"),
                    available=available,
                    identifier=str(product.get("id") or product.get("handle") or "")
                    or None,
                    canonical_url=product.get("_merchant_url"),
                    has_structured_product=True,
                )
            )

    if not candidates:
        meta_product = extract_product_from_meta(html, product_url=final_url)
        if meta_product:
            price, regular, currency, available = _prices_from_mapping(meta_product)
            candidates.append(
                ParsedProduct(
                    title=meta_product.get("title"),
                    current_price=price,
                    regular_price=regular,
                    currency=currency or meta_product.get("_currency"),
                    available=available,
                    identifier=str(
                        meta_product.get("id") or meta_product.get("handle") or ""
                    )
                    or None,
                    canonical_url=meta_product.get("_merchant_url"),
                    has_structured_product=True,
                )
            )

    if candidates:
        exact_candidates = [
            item
            for item in candidates
            if urls_match_product_identity(item.canonical_url, final_url)
        ]
        best = max(
            exact_candidates or candidates,
            key=lambda item: sum(
                value is not None
                for value in (
                    item.title,
                    item.current_price,
                    item.currency,
                    item.identifier,
                    item.canonical_url,
                )
            ),
        )
    else:
        best = ParsedProduct()
    return _merge_page_context(best, parser=parser, final_url=final_url)


class ProductRefreshService:
    def __init__(
        self,
        db: Session,
        *,
        http_client: Any | None = None,
        url_validator: Callable[[str], str] = _assert_public_host,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        checked_at: datetime | None = None,
    ) -> None:
        self.db = db
        self.http_client = http_client or requests.Session()
        self.url_validator = url_validator
        self.timeout_seconds = timeout_seconds
        self.checked_at = checked_at or datetime.now(timezone.utc)

    def _fetch(self, raw_url: str | None) -> PageInspection:
        requested_url = clean_stored_url(raw_url)
        if not requested_url:
            return PageInspection(
                status=RefreshStatus.PARSE_FAILURE,
                reason="No original merchant product URL is stored.",
                requested_url=None,
            )
        current_url = requested_url
        redirect_count = 0
        for _ in range(MAX_REDIRECTS + 1):
            try:
                current_url = self.url_validator(current_url)
            except Exception as exc:  # noqa: BLE001 - invalid stored URLs are reportable
                return PageInspection(
                    status=RefreshStatus.PARSE_FAILURE,
                    reason=f"The stored URL is not a safe public URL: {exc}",
                    requested_url=requested_url,
                    final_url=current_url,
                    redirect_count=redirect_count,
                )
            try:
                response = self.http_client.get(
                    current_url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": (
                            "text/html,application/xhtml+xml,"
                            "application/json;q=0.9,*/*;q=0.8"
                        ),
                    },
                    timeout=self.timeout_seconds,
                    allow_redirects=False,
                )
            except (requests.RequestException, OSError) as exc:
                return PageInspection(
                    status=RefreshStatus.TEMPORARY_FAILURE,
                    reason=f"The merchant request failed temporarily: {type(exc).__name__}.",
                    requested_url=requested_url,
                    final_url=current_url,
                    redirect_count=redirect_count,
                )

            status_code = int(response.status_code)
            if 300 <= status_code < 400:
                location = response.headers.get("Location")
                if not location:
                    return PageInspection(
                        status=RefreshStatus.PARSE_FAILURE,
                        reason="The merchant returned a redirect without a destination.",
                        requested_url=requested_url,
                        final_url=current_url,
                        redirect_count=redirect_count,
                    )
                redirect_count += 1
                current_url = urljoin(current_url, location)
                continue
            if status_code in {404, 410}:
                return PageInspection(
                    status=RefreshStatus.PRODUCT_UNAVAILABLE,
                    reason=f"The original merchant URL returned HTTP {status_code}.",
                    requested_url=requested_url,
                    final_url=current_url,
                    confidence="high",
                    redirect_count=redirect_count,
                )
            if status_code in {403, 429}:
                return PageInspection(
                    status=RefreshStatus.BLOCKED_OR_UNKNOWN,
                    reason=f"The merchant blocked or rate-limited the check (HTTP {status_code}).",
                    requested_url=requested_url,
                    final_url=current_url,
                    confidence="low",
                    redirect_count=redirect_count,
                )
            if status_code >= 500:
                return PageInspection(
                    status=RefreshStatus.TEMPORARY_FAILURE,
                    reason=f"The merchant returned a temporary HTTP {status_code} response.",
                    requested_url=requested_url,
                    final_url=current_url,
                    confidence="low",
                    redirect_count=redirect_count,
                )
            if status_code >= 400:
                return PageInspection(
                    status=RefreshStatus.BLOCKED_OR_UNKNOWN,
                    reason=f"The merchant returned HTTP {status_code}; availability is unknown.",
                    requested_url=requested_url,
                    final_url=current_url,
                    confidence="low",
                    redirect_count=redirect_count,
                )

            body = bytes(response.content or b"")
            if len(body) > MAX_PRODUCT_PAGE_BYTES:
                return PageInspection(
                    status=RefreshStatus.PARSE_FAILURE,
                    reason="The merchant page exceeded the safe parsing size limit.",
                    requested_url=requested_url,
                    final_url=current_url,
                    redirect_count=redirect_count,
                )
            content_type = str(response.headers.get("Content-Type") or "").lower()
            charset_match = re.search(r"charset=([^\s;]+)", content_type)
            charset = charset_match.group(1).strip("\"'") if charset_match else "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            lowered = html.lower()
            if any(marker in lowered for marker in BOT_MARKERS):
                return PageInspection(
                    status=RefreshStatus.BLOCKED_OR_UNKNOWN,
                    reason="The merchant returned a CAPTCHA or bot-protection page.",
                    requested_url=requested_url,
                    final_url=current_url,
                    confidence="low",
                    redirect_count=redirect_count,
                )
            parsed = _extract_product(html, final_url=current_url)
            return PageInspection(
                status=None,
                reason="The merchant page was fetched.",
                requested_url=requested_url,
                final_url=current_url,
                parsed=parsed,
                confidence="medium",
                redirect_count=redirect_count,
            )

        return PageInspection(
            status=RefreshStatus.TEMPORARY_FAILURE,
            reason="The merchant exceeded the redirect limit.",
            requested_url=requested_url,
            final_url=current_url,
            redirect_count=redirect_count,
        )

    def _classify_original(
        self,
        product: Product,
        inspection: PageInspection,
    ) -> tuple[RefreshStatus, str, str, bool, bool]:
        if inspection.status is not None:
            return (
                inspection.status,
                inspection.confidence,
                inspection.reason,
                False,
                inspection.status in REVIEW_STATUSES,
            )

        parsed = inspection.parsed
        title_similarity = max(
            _title_similarity(product.name, parsed.title),
            _title_similarity(product.name, parsed.page_title),
        )
        canonical_is_home = _is_homepage_url(parsed.canonical_url)
        redirected_home = (
            inspection.redirect_count > 0
            and _is_homepage_url(inspection.final_url)
        )
        redirected_collection = (
            inspection.redirect_count > 0
            and _is_collection_url(inspection.final_url)
        )
        no_product_match = (
            not parsed.has_structured_product and title_similarity < 0.45
        )

        if redirected_home and no_product_match:
            evidence = [
                "the final path is the merchant homepage",
                "no Product structured data remains",
                "the returned title does not match the stored product",
            ]
            if canonical_is_home:
                evidence.append("the canonical URL is also the homepage")
            return (
                RefreshStatus.PRODUCT_UNAVAILABLE,
                "high",
                "Homepage redirect detected: " + "; ".join(evidence) + ".",
                False,
                True,
            )
        if redirected_collection and no_product_match:
            return (
                RefreshStatus.LIKELY_UNAVAILABLE,
                "high",
                "The product URL redirected to a collection or search page with no matching product data.",
                False,
                True,
            )
        if (
            any(marker in parsed.page_text for marker in UNAVAILABLE_MARKERS)
            and not parsed.has_structured_product
        ):
            return (
                RefreshStatus.PRODUCT_UNAVAILABLE,
                "high",
                "The merchant page contains explicit product-unavailable language and no Product data.",
                False,
                True,
            )
        if parsed.available is False:
            return (
                RefreshStatus.LIKELY_UNAVAILABLE,
                "medium",
                "The product page still exists, but its structured availability is out of stock.",
                False,
                True,
            )
        if not parsed.has_structured_product:
            return (
                RefreshStatus.PARSE_FAILURE,
                "low",
                "The URL returned a page, but no page-level Product data could be verified.",
                False,
                True,
            )

        identity_evidence = 0
        if urls_match_product_identity(inspection.requested_url, inspection.final_url):
            identity_evidence += 2
        if urls_match_product_identity(inspection.requested_url, parsed.canonical_url):
            identity_evidence += 2
        if title_similarity >= 0.55:
            identity_evidence += 2
        requested_identifiers = _product_path_identifiers(
            inspection.requested_url
        )
        destination_identifiers = _product_path_identifiers(
            parsed.canonical_url or inspection.final_url
        )
        if requested_identifiers & destination_identifiers:
            identity_evidence += 2
        requested_host = (
            urlparse(inspection.requested_url or "").hostname or ""
        ).lower().removeprefix("www.")
        destination_host = (
            urlparse(inspection.final_url or "").hostname or ""
        ).lower().removeprefix("www.")
        if (
            requested_host
            and requested_host == destination_host
            and _looks_like_product_url(inspection.requested_url)
            and _looks_like_product_url(inspection.final_url)
            and title_similarity >= 0.55
        ):
            identity_evidence += 1
        identifier = str(parsed.identifier or "").lower()
        if identifier and (
            identifier in str(product.external_id or "").lower()
            or identifier in urlparse(inspection.requested_url or "").path.lower()
        ):
            identity_evidence += 1
        confidence = "high" if identity_evidence >= 3 else "medium"

        detected_currency = parsed.currency or product.currency
        if (
            parsed.currency
            and product.currency
            and parsed.currency.upper() != product.currency.upper()
        ):
            return (
                RefreshStatus.PARSE_FAILURE,
                confidence,
                (
                    f"The merchant reported {parsed.currency}, but Haroona stores "
                    f"{product.currency}; the price was not applied."
                ),
                False,
                True,
            )
        if parsed.current_price is None:
            return (
                RefreshStatus.PARSE_FAILURE,
                confidence,
                "The product identity was found, but no current price could be extracted.",
                False,
                True,
            )

        stored_price = (
            Decimal(product.price) if product.price is not None else None
        )
        stored_regular = (
            Decimal(product.regular_price)
            if product.regular_price is not None
            else None
        )
        price_changed = stored_price != parsed.current_price
        regular_changed = (
            parsed.regular_price is not None
            and stored_regular != parsed.regular_price
        )
        if price_changed or regular_changed:
            safe = confidence == "high" and bool(detected_currency)
            return (
                RefreshStatus.PRICE_CHANGED,
                confidence,
                (
                    "A current merchant price differs from Haroona and is safe to apply."
                    if safe
                    else "A price difference was found, but product identity confidence is not high enough to apply it."
                ),
                safe,
                not safe,
            )
        return (
            RefreshStatus.UNCHANGED,
            confidence,
            "The product identity, currency, and current price match Haroona.",
            False,
            False,
        )

    def _check_affiliate(
        self,
        product: Product,
        *,
        original: PageInspection,
    ) -> tuple[str, str | None, str | None]:
        affiliate_url = clean_stored_url(product.affiliate_url)
        merchant_url = clean_stored_url(product.merchant_url)
        if not affiliate_url:
            return "not_present", None, None
        if urls_match_product_identity(affiliate_url, merchant_url):
            return "working", affiliate_url, None

        inspection = self._fetch(affiliate_url)
        if inspection.status in {
            RefreshStatus.PRODUCT_UNAVAILABLE,
            RefreshStatus.LIKELY_UNAVAILABLE,
        }:
            return (
                RefreshStatus.AFFILIATE_LINK_BROKEN.value,
                inspection.final_url,
                "The affiliate link failed, while the original merchant page remained valid.",
            )
        if inspection.status is not None:
            return inspection.status.value, inspection.final_url, inspection.reason

        parsed = inspection.parsed
        title_similarity = max(
            _title_similarity(product.name, parsed.title),
            _title_similarity(product.name, parsed.page_title),
        )
        destination_matches = (
            urls_match_product_identity(inspection.final_url, merchant_url)
            or urls_match_product_identity(parsed.canonical_url, merchant_url)
        )
        generic_destination = (
            _is_homepage_url(inspection.final_url)
            or _is_collection_url(inspection.final_url)
            or _is_homepage_url(parsed.canonical_url)
        )
        if destination_matches or (
            parsed.has_structured_product and title_similarity >= 0.55
        ):
            return "working", inspection.final_url, None
        if generic_destination and title_similarity < 0.45:
            return (
                RefreshStatus.AFFILIATE_LINK_BROKEN.value,
                inspection.final_url,
                "The affiliate link redirects to a generic merchant page, while the original product page remains valid.",
            )
        return (
            RefreshStatus.PARSE_FAILURE.value,
            inspection.final_url,
            "The affiliate destination could not be verified as the same product.",
        )

    def check_product(self, product: Product) -> ProductRefreshItem:
        original = self._fetch(product.merchant_url)
        status, confidence, reason, would_update, would_flag = (
            self._classify_original(product, original)
        )
        affiliate_status = "not_checked"
        affiliate_final_url = None
        if status in SUCCESS_STATUSES:
            affiliate_status, affiliate_final_url, affiliate_reason = (
                self._check_affiliate(product, original=original)
            )
            if affiliate_status == RefreshStatus.AFFILIATE_LINK_BROKEN.value:
                status = RefreshStatus.AFFILIATE_LINK_BROKEN
                confidence = "high"
                reason = affiliate_reason or reason
                would_flag = True
            elif affiliate_reason:
                reason = f"{reason} Affiliate check: {affiliate_reason}"

        parsed = original.parsed
        merchant = (
            product.brand.name
            if getattr(product, "brand", None) is not None
            else str(product.source or "Unknown")
        )
        return ProductRefreshItem(
            product_id=product.id,
            merchant=merchant,
            stored_title=product.name,
            stored_price=(
                Decimal(product.price) if product.price is not None else None
            ),
            detected_price=parsed.current_price,
            stored_regular_price=(
                Decimal(product.regular_price)
                if product.regular_price is not None
                else None
            ),
            detected_regular_price=parsed.regular_price,
            currency=product.currency,
            detected_currency=parsed.currency or product.currency,
            original_url=clean_stored_url(product.merchant_url),
            affiliate_url=clean_stored_url(product.affiliate_url),
            final_url=original.final_url,
            affiliate_final_url=affiliate_final_url,
            refresh_status=status,
            affiliate_status=affiliate_status,
            confidence=confidence,
            reason=reason,
            would_update=would_update,
            would_flag_for_review=would_flag,
        )

    def apply_result(
        self,
        product: Product,
        result: ProductRefreshItem,
    ) -> None:
        old_price = product.price
        old_regular_price = product.regular_price
        if result.would_update and result.detected_price is not None:
            product.price = result.detected_price
            if result.detected_regular_price is not None:
                product.regular_price = result.detected_regular_price
            if result.detected_currency:
                product.currency = result.detected_currency

        price_changed = (
            old_price != product.price
            or old_regular_price != product.regular_price
        )
        if price_changed:
            self.db.add(
                ProductPriceSnapshot(
                    product_id=product.id,
                    source=product.source,
                    external_id=product.external_id,
                    old_price=old_price,
                    new_price=product.price,
                    old_regular_price=old_regular_price,
                    new_regular_price=product.regular_price,
                    old_availability_status=product.availability_status,
                    new_availability_status=product.availability_status,
                    checked_at=self.checked_at,
                )
            )

        product.last_product_checked_at = self.checked_at
        product.last_link_checked_at = self.checked_at
        if result.detected_price is not None:
            product.last_price_checked_at = self.checked_at
        product.last_refresh_status = result.refresh_status.value
        product.price_check_status = result.refresh_status.value
        error = (
            None
            if result.refresh_status in SUCCESS_STATUSES
            else result.reason[:2000]
        )
        product.last_refresh_error = error
        product.price_check_error = error

        if result.refresh_status in SUCCESS_STATUSES:
            product.last_seen_available_at = self.checked_at
            product.consecutive_refresh_failures = 0
            if not result.would_flag_for_review:
                product.needs_refresh_review = False
        else:
            product.consecutive_refresh_failures = (
                int(product.consecutive_refresh_failures or 0) + 1
            )
            if result.would_flag_for_review:
                product.needs_refresh_review = True

        # Deliberately do not change is_active, deactivated_at, or URLs here.

    def select_products(
        self,
        *,
        product_id: int | None = None,
        merchant: str | None = None,
        limit: int | None = 20,
        all_products: bool = False,
    ) -> list[Product]:
        query = (
            self.db.query(Product)
            .outerjoin(Brand, Product.brand_id == Brand.id)
            .filter(Product.is_active.is_(True))
            .order_by(Product.id.asc())
        )
        if product_id is not None:
            query = query.filter(Product.id == product_id)
        if merchant:
            query = query.filter(Brand.name.ilike(f"%{merchant.strip()}%"))
        if not all_products and limit is not None:
            query = query.limit(limit)
        return query.all()

    def run(
        self,
        products: Iterable[Product],
        *,
        apply: bool = False,
    ) -> ProductRefreshReport:
        results: list[ProductRefreshItem] = []
        for product in products:
            result = self.check_product(product)
            results.append(result)
            if apply:
                self.apply_result(product, result)
        return ProductRefreshReport(
            mode="apply" if apply else "dry_run",
            generated_at=self.checked_at,
            results=tuple(results),
        )

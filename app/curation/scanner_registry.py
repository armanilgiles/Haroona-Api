from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.curation.lilysilk_category import scan_and_save_lilysilk_category
from app.curation.shopcider_category import scan_and_save_shopcider_category
from app.curation.shopify_collection import CollectionScanOptions, scan_and_save_shopify_collection
from app.curation.source_scan_guardrails import get_scanner_image_capabilities

ScanFunction = Callable[[Session, CollectionScanOptions], dict[str, Any]]

_SHOPCIDER_CATEGORY_PATTERN = re.compile(r"^/category/[^/?#]+-cid-\d+/?$", re.IGNORECASE)
_SHOPCIDER_COLLECTION_PATTERN = re.compile(r"^/collection/[^/?#]+/?$", re.IGNORECASE)
_LILYSILK_CATEGORY_PATTERN = re.compile(
    r"^/[a-z]{2}/category/[^/?#]+\.html/?$",
    re.IGNORECASE,
)

SUPPORTED_SCANNER_EXAMPLES = (
    "Shopify collection URL containing /collections/{handle}",
    "ShopCider category URL like https://www.shopcider.com/category/maxi-dresses-cid-3587",
    "ShopCider collection URL like https://www.shopcider.com/collection/top",
    "LILYSILK category URL like https://www.lilysilk.com/us/category/womentops.html",
    "Public collection, category, or listing URL that exposes structured products or product links",
)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_disallowed_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


@dataclass(frozen=True)
class ScannerMatch:
    name: str
    source: str
    source_type: str
    scan: ScanFunction
    supported_image_modes: tuple[str, ...]
    default_image_mode: str

    def resolve_image_mode(self, requested_mode: str) -> str:
        if requested_mode in self.supported_image_modes:
            return requested_mode
        return self.default_image_mode


class UnsupportedScannerError(ValueError):
    """Raised when Curate Studio receives a URL that has no scanner yet."""

    def __init__(self, source_url: str, reason: str | None = None) -> None:
        parsed = urlparse(source_url.strip())
        host = parsed.netloc.lower() or "missing domain"
        path = parsed.path or "/"
        supported = "; ".join(SUPPORTED_SCANNER_EXAMPLES)

        message = (
            "Unsupported Curate Studio URL. "
            f"Detected host '{host}' and path '{path}'. "
            f"{reason + ' ' if reason else ''}"
            f"Supported scanners: {supported}."
        )
        super().__init__(message)
        self.source_url = source_url
        self.host = host
        self.path = path
        self.supported_scanners = SUPPORTED_SCANNER_EXAMPLES


def detect_curation_scanner(source_url: str) -> ScannerMatch:
    """Pick the right product scanner based on the submitted Curate Studio URL."""
    parsed = urlparse(source_url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()

    if parsed.scheme not in {"http", "https"} or not host:
        raise UnsupportedScannerError(source_url, "The URL must include http(s) and a domain.")
    if _is_disallowed_host(host):
        raise UnsupportedScannerError(
            source_url,
            "Private and local network addresses cannot be scanned.",
        )

    if _host_matches(host, "shopcider.com"):
        if _SHOPCIDER_CATEGORY_PATTERN.match(path):
            supported_image_modes, default_image_mode = get_scanner_image_capabilities(
                "shopcider_category"
            )
            return ScannerMatch(
                name="shopcider_category",
                source="shopcider",
                source_type="category",
                scan=scan_and_save_shopcider_category,
                supported_image_modes=supported_image_modes,
                default_image_mode=default_image_mode,
            )
        if _SHOPCIDER_COLLECTION_PATTERN.match(path):
            supported_image_modes, default_image_mode = get_scanner_image_capabilities(
                "shopcider_collection"
            )
            return ScannerMatch(
                name="shopcider_collection",
                source="shopcider",
                source_type="collection",
                scan=scan_and_save_shopcider_category,
                supported_image_modes=supported_image_modes,
                default_image_mode=default_image_mode,
            )
        raise UnsupportedScannerError(
            source_url,
            "ShopCider is supported for /category/{slug}-cid-{id} and /collection/{slug} pages.",
        )

    if _host_matches(host, "lilysilk.com"):
        if _LILYSILK_CATEGORY_PATTERN.match(path):
            supported_image_modes, default_image_mode = get_scanner_image_capabilities(
                "lilysilk_category"
            )
            return ScannerMatch(
                name="lilysilk_category",
                source="lilysilk",
                source_type="category",
                scan=scan_and_save_lilysilk_category,
                supported_image_modes=supported_image_modes,
                default_image_mode=default_image_mode,
            )
        raise UnsupportedScannerError(
            source_url,
            "LILYSILK is supported for /{store}/category/{slug}.html pages.",
        )

    if "/collections/" in path:
        supported_image_modes, default_image_mode = get_scanner_image_capabilities(
            "shopify_collection"
        )
        return ScannerMatch(
            name="shopify_collection",
            source="shopify",
            source_type="collection",
            scan=scan_and_save_shopify_collection,
            supported_image_modes=supported_image_modes,
            default_image_mode=default_image_mode,
        )

    supported_image_modes, default_image_mode = get_scanner_image_capabilities(
        "generic_storefront"
    )
    return ScannerMatch(
        name="generic_storefront",
        source="storefront",
        source_type="collection",
        scan=scan_and_save_shopify_collection,
        supported_image_modes=supported_image_modes,
        default_image_mode=default_image_mode,
    )

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.curation.shopcider_category import scan_and_save_shopcider_category
from app.curation.shopify_collection import CollectionScanOptions, scan_and_save_shopify_collection

ScanFunction = Callable[[Session, CollectionScanOptions], dict[str, Any]]

_SHOPCIDER_CATEGORY_PATTERN = re.compile(r"^/category/[^/?#]+-cid-\d+/?$", re.IGNORECASE)
_SHOPCIDER_COLLECTION_PATTERN = re.compile(r"^/collection/[^/?#]+/?$", re.IGNORECASE)

SUPPORTED_SCANNER_EXAMPLES = (
    "Shopify collection URL containing /collections/{handle}",
    "ShopCider category URL like https://www.shopcider.com/category/maxi-dresses-cid-3587",
    "ShopCider collection URL like https://www.shopcider.com/collection/top",
)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


@dataclass(frozen=True)
class ScannerMatch:
    name: str
    source: str
    source_type: str
    scan: ScanFunction


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
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if parsed.scheme not in {"http", "https"} or not host:
        raise UnsupportedScannerError(source_url, "The URL must include http(s) and a domain.")

    if _host_matches(host, "shopcider.com"):
        if _SHOPCIDER_CATEGORY_PATTERN.match(path):
            return ScannerMatch(
                name="shopcider_category",
                source="shopcider",
                source_type="category",
                scan=scan_and_save_shopcider_category,
            )
        if _SHOPCIDER_COLLECTION_PATTERN.match(path):
            return ScannerMatch(
                name="shopcider_collection",
                source="shopcider",
                source_type="collection",
                scan=scan_and_save_shopcider_category,
            )
        raise UnsupportedScannerError(
            source_url,
            "ShopCider is supported for /category/{slug}-cid-{id} and /collection/{slug} pages.",
        )

    if "/collections/" in path:
        return ScannerMatch(
            name="shopify_collection",
            source="shopify",
            source_type="collection",
            scan=scan_and_save_shopify_collection,
        )

    raise UnsupportedScannerError(source_url)

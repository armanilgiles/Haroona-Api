from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.curation.merchant_profiles import normalize_merchant_key


FALLBACK_CATEGORIES = (
    "dress",
    "tops",
    "bottoms",
    "co-ords",
    "shoes",
    "bags",
    "accessories",
    "jewelry",
)

SCANNER_IMAGE_CAPABILITIES: dict[str, tuple[tuple[str, ...], str]] = {
    "shopify_collection": (("fast", "smart", "model_only"), "smart"),
    "shopcider_category": (("fast", "smart", "model_only"), "smart"),
    "shopcider_collection": (("fast", "smart", "model_only"), "smart"),
    "lilysilk_category": (("fast", "smart"), "smart"),
}

_CATEGORY_ALIASES: dict[str, str | None] = {
    "": None,
    "auto": None,
    "auto-detect": None,
    "dress": "dress",
    "dresses": "dress",
    "gown": "dress",
    "gowns": "dress",
    "top": "tops",
    "tops": "tops",
    "shirt": "tops",
    "shirts": "tops",
    "bottom": "bottoms",
    "bottoms": "bottoms",
    "pants": "bottoms",
    "trousers": "bottoms",
    "skirts": "bottoms",
    "set": "co-ords",
    "sets": "co-ords",
    "co-ord": "co-ords",
    "co-ords": "co-ords",
    "co ord": "co-ords",
    "co ords": "co-ords",
    "shoe": "shoes",
    "shoes": "shoes",
    "footwear": "shoes",
    "bag": "bags",
    "bags": "bags",
    "accessory": "accessories",
    "accessories": "accessories",
    "jewellery": "jewelry",
    "jewelry": "jewelry",
}


@dataclass(frozen=True)
class MerchantSourceIdentity:
    merchant_key: str
    display_name: str
    domains: tuple[str, ...]
    accepted_name_keys: tuple[str, ...] = ()


KNOWN_MERCHANT_SOURCES = (
    MerchantSourceIdentity(
        merchant_key="nobodys-child",
        display_name="Nobody's Child",
        domains=("nobodyschild.com",),
    ),
    MerchantSourceIdentity(
        merchant_key="shopcider",
        display_name="Cider",
        domains=("shopcider.com",),
        accepted_name_keys=("cider", "shop-cider"),
    ),
    MerchantSourceIdentity(
        merchant_key="romwe",
        display_name="ROMWE",
        domains=("romwe.com",),
    ),
    MerchantSourceIdentity(
        merchant_key="rainbow",
        display_name="Rainbow Shops",
        domains=("rainbowshops.com",),
        accepted_name_keys=("rainbow-shops", "rainbowshops"),
    ),
    MerchantSourceIdentity(
        merchant_key="lilysilk",
        display_name="LILYSILK",
        domains=("lilysilk.com",),
    ),
    MerchantSourceIdentity(
        merchant_key="beams",
        display_name="BEAMS",
        domains=("beams.co.jp",),
    ),
    MerchantSourceIdentity(
        merchant_key="musinsa",
        display_name="MUSINSA",
        domains=("musinsa.com",),
    ),
)


@dataclass(frozen=True)
class MerchantSourceGuidance:
    source_host: str
    verification: str
    submitted_name: str
    resolved_name: str
    suggested_name: str | None = None
    message: str | None = None


def clean_merchant_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_category_hint(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(r"\s+", " ", value).strip().lower().replace("_", "-")
    if normalized in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[normalized]

    accepted = ", ".join(FALLBACK_CATEGORIES)
    raise ValueError(
        f"Unsupported fallback category '{value}'. Use auto-detect or one of: {accepted}."
    )


def get_scanner_image_capabilities(scanner_name: str) -> tuple[tuple[str, ...], str]:
    return SCANNER_IMAGE_CAPABILITIES.get(scanner_name, (("fast",), "fast"))


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _identity_for_host(host: str) -> MerchantSourceIdentity | None:
    for identity in KNOWN_MERCHANT_SOURCES:
        if any(_host_matches(host, domain) for domain in identity.domains):
            return identity
    return None


def _merchant_matches_identity(
    merchant_name: str,
    identity: MerchantSourceIdentity,
) -> bool:
    merchant_key = normalize_merchant_key(merchant_name)
    accepted_keys = {
        identity.merchant_key,
        normalize_merchant_key(identity.display_name),
        *(normalize_merchant_key(value) for value in identity.accepted_name_keys),
    }
    return merchant_key in accepted_keys


def get_merchant_source_guidance(
    source_url: str,
    merchant_name: str,
) -> MerchantSourceGuidance:
    host = (urlparse(source_url.strip()).hostname or "").lower()
    cleaned_name = clean_merchant_name(merchant_name)
    identity = _identity_for_host(host)

    if identity is None:
        return MerchantSourceGuidance(
            source_host=host,
            verification="unverified",
            submitted_name=cleaned_name,
            resolved_name=cleaned_name,
            message=(
                f"Haroona does not have a saved merchant identity for {host or 'this URL'} yet. "
                "Confirm the merchant name before scanning."
            ),
        )

    if not _merchant_matches_identity(cleaned_name, identity):
        return MerchantSourceGuidance(
            source_host=host,
            verification="conflict",
            submitted_name=cleaned_name,
            resolved_name=cleaned_name,
            suggested_name=identity.display_name,
            message=(
                f"Merchant '{cleaned_name}' does not match the known source domain {host}. "
                f"Use '{identity.display_name}' for this scan."
            ),
        )

    return MerchantSourceGuidance(
        source_host=host,
        verification="verified",
        submitted_name=cleaned_name,
        resolved_name=identity.display_name,
        suggested_name=identity.display_name,
        message=f"Merchant verified from {host}.",
    )

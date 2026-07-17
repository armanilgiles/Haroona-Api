from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

from app.curation.merchant_profiles import get_merchant_profile, normalize_merchant_key


PLATFORM_ALIGNMENT_THRESHOLD = Decimal("7.0")


@dataclass(frozen=True)
class PlatformAlignmentResult:
    score: Decimal
    reasons: list[str]
    component_scores: dict[str, Decimal]

    @property
    def passes(self) -> bool:
        return self.score >= PLATFORM_ALIGNMENT_THRESHOLD


EDITORIAL_BRAND_SCORES: dict[str, Decimal] = {
    "beams": Decimal("8.5"),
    "burberry": Decimal("9.5"),
    "diane-von-furstenberg": Decimal("9.0"),
    "dvf": Decimal("9.0"),
    "ganni": Decimal("8.5"),
    "gucci": Decimal("9.5"),
    "jacquemus": Decimal("9.0"),
    "lilysilk": Decimal("8.0"),
    "nobody-s-child": Decimal("8.0"),
    "nobodys-child": Decimal("8.0"),
    "reformation": Decimal("8.5"),
    "staud": Decimal("8.5"),
    "teri-jon": Decimal("8.0"),
}

LOW_TRUST_BRAND_SCORES: dict[str, Decimal] = {
    "fashnzfab": Decimal("4.0"),
    "romwe": Decimal("3.5"),
    "shein": Decimal("3.0"),
    "temu": Decimal("2.5"),
}

PREMIUM_MATERIALS = (
    "cashmere",
    "organic cotton",
    "organic linen",
    "linen",
    "silk",
    "selvedge denim",
    "raw denim",
    "wool",
    "leather",
    "heavy gauge knit",
)

INTENTIONAL_SILHOUETTES = (
    "asymmetrical",
    "asymmetric",
    "architectural",
    "deconstructed",
    "draped",
    "pleated",
    "sculptural",
    "structured",
    "tailored",
    "wrap dress",
)

LOWER_INTEGRITY_SIGNALS = (
    "acrylic",
    "faux leather",
    "paper thin",
    "polyester",
    "synthetic",
)

COMMON_CONSTRUCTION_SIGNALS = (
    "elastic waist",
    "smocked",
    "tiered ruffle",
)


def _normalize_text(value: str | None) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip() + " "


def _contains(haystack: str, keyword: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", keyword.lower()).strip()
    return bool(normalized) and f" {normalized} " in haystack


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal("1.0"), min(Decimal("10.0"), value))


def _recognized_brand_score(
    *,
    brand_name: str | None,
    title: str,
) -> tuple[Decimal | None, str | None]:
    candidates = [brand_name or "", title]
    for candidate in candidates:
        normalized = normalize_merchant_key(candidate)
        for brand_key, score in EDITORIAL_BRAND_SCORES.items():
            if brand_key in normalized:
                return score, brand_key
        for brand_key, score in LOW_TRUST_BRAND_SCORES.items():
            if brand_key in normalized:
                return score, brand_key
    return None, None


def score_platform_alignment(
    *,
    title: str,
    description: str | None,
    product_type: str | None,
    tags: list[str] | None,
    merchant_name: str | None,
    brand_name: str | None,
    merchant_verification: str,
    image_url: str | None,
    image_quality_score: int | None,
    normalized_category: str | None,
    city_fit_score: int,
) -> PlatformAlignmentResult:
    text = _normalize_text(
        " ".join(
            [
                title or "",
                description or "",
                product_type or "",
                " ".join(tags or []),
            ]
        )
    )

    recognized_brand_score, recognized_brand_key = _recognized_brand_score(
        brand_name=brand_name,
        title=title,
    )
    merchant_profile = (
        get_merchant_profile(merchant_name)
        if merchant_verification == "verified"
        else None
    )

    if recognized_brand_score is not None:
        trust_score = recognized_brand_score
        trust_reason = f"recognized brand: {recognized_brand_key}"
    elif merchant_profile is not None:
        trust_score = Decimal(
            str((merchant_profile.quality_score + merchant_profile.haroona_fit_score) / 2)
        )
        trust_reason = f"verified merchant profile: {merchant_profile.display_name}"
    elif merchant_verification == "verified":
        trust_score = Decimal("6.0")
        trust_reason = "verified merchant without an editorial brand profile"
    else:
        trust_score = Decimal("5.0")
        trust_reason = "unverified marketplace or brand identity"

    if not image_url:
        photo_score = Decimal("1.0")
        photo_reason = "missing product image"
    elif image_quality_score is None:
        photo_score = Decimal("7.0")
        photo_reason = "verified product image; visual grade pending"
    elif image_quality_score >= 80:
        photo_score = Decimal("8.5")
        photo_reason = "strong catalog-image signal"
    elif image_quality_score >= 65:
        photo_score = Decimal("7.5")
        photo_reason = "good catalog-image signal"
    elif image_quality_score >= 45:
        photo_score = Decimal("6.5")
        photo_reason = "usable catalog image"
    else:
        photo_score = Decimal("5.5")
        photo_reason = "weak catalog-image signal"

    premium_hits = [keyword for keyword in PREMIUM_MATERIALS if _contains(text, keyword)]
    silhouette_hits = [
        keyword for keyword in INTENTIONAL_SILHOUETTES if _contains(text, keyword)
    ]
    lower_hits = [keyword for keyword in LOWER_INTEGRITY_SIGNALS if _contains(text, keyword)]
    common_hits = [keyword for keyword in COMMON_CONSTRUCTION_SIGNALS if _contains(text, keyword)]
    material_score = Decimal("5.5")
    material_score += Decimal(str(min(len(premium_hits), 3))) * Decimal("0.7")
    material_score += Decimal(str(min(len(silhouette_hits), 4))) * Decimal("0.4")
    material_score -= Decimal(str(min(len(lower_hits), 3))) * Decimal("0.6")
    material_score -= Decimal(str(min(len(common_hits), 2))) * Decimal("0.35")
    material_score = _clamp(material_score)
    material_signals = [*premium_hits[:2], *silhouette_hits[:2]]
    material_reason = (
        "intentional material/silhouette: " + ", ".join(material_signals)
        if material_signals
        else "limited premium material or silhouette evidence"
    )
    if lower_hits or common_hits:
        deductions = [*lower_hits[:2], *common_hits[:2]]
        material_reason += "; deductions: " + ", ".join(deductions)

    utility_score = Decimal("5.0")
    if merchant_profile is not None and merchant_profile.origin_city_slug:
        utility_score += Decimal("2.5")
        utility_reason = "native city/brand connection"
    elif recognized_brand_score is not None:
        utility_score += Decimal("1.5")
        utility_reason = "recognized brand supports curation context"
    else:
        utility_reason = "city-inspired placement only"
    if city_fit_score >= 80:
        utility_score += Decimal("1.5")
    elif city_fit_score >= 70:
        utility_score += Decimal("1.0")
    elif city_fit_score >= 60:
        utility_score += Decimal("0.5")
    if normalized_category:
        utility_score += Decimal("0.3")
    utility_score = _clamp(utility_score)

    component_scores = {
        "trust_brand": _clamp(trust_score),
        "photography": _clamp(photo_score),
        "material_silhouette": material_score,
        "curation_utility": utility_score,
    }
    weighted_score = (
        component_scores["trust_brand"] * Decimal("0.30")
        + component_scores["photography"] * Decimal("0.20")
        + component_scores["material_silhouette"] * Decimal("0.30")
        + component_scores["curation_utility"] * Decimal("0.20")
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    reasons = [
        f"Trust & brand {component_scores['trust_brand']}/10 — {trust_reason}",
        f"Photography {component_scores['photography']}/10 — {photo_reason}",
        f"Material & silhouette {component_scores['material_silhouette']}/10 — {material_reason}",
        f"Curation utility {component_scores['curation_utility']}/10 — {utility_reason}",
    ]
    reasons.append(
        "Platform threshold passed"
        if weighted_score >= PLATFORM_ALIGNMENT_THRESHOLD
        else f"Below Haroona's {PLATFORM_ALIGNMENT_THRESHOLD}/10 platform threshold"
    )

    return PlatformAlignmentResult(
        score=weighted_score,
        reasons=reasons,
        component_scores=component_scores,
    )


def platform_alignment_passes(value: Decimal | int | float | str | None) -> bool:
    if value is None:
        return False
    return Decimal(str(value)) >= PLATFORM_ALIGNMENT_THRESHOLD

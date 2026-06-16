from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MerchantProfile:
    """Store-level taste context used by the Haroona curation score.

    This keeps product scoring from treating every store the same. A cotton midi
    dress from a London-coded conscious brand should be understood differently
    than a similar product from a random fast-fashion marketplace.
    """

    merchant_key: str
    display_name: str
    origin_city_slug: str | None = None
    origin_country: str | None = None
    source_type: str | None = None
    brand_vibes: tuple[str, ...] = ()
    aspiration: str | None = None
    best_city_slugs: tuple[str, ...] = ()
    compatible_city_slugs: tuple[str, ...] = ()
    weaker_city_slugs: tuple[str, ...] = ()
    quality_score: int = 5
    haroona_fit_score: int = 5


@dataclass(frozen=True)
class MerchantFitResult:
    score_adjustment: int
    reasons: list[str]
    city_connection_type: str | None
    city_connection_note: str | None
    profile: MerchantProfile | None = None


MERCHANT_PROFILES: dict[str, MerchantProfile] = {
    "nobodys-child": MerchantProfile(
        merchant_key="nobodys-child",
        display_name="Nobody's Child",
        origin_city_slug="london",
        origin_country="UK",
        source_type="city_based_brand",
        brand_vibes=("conscious", "feminine", "soft-city", "modern-romantic", "natural-fabrics"),
        aspiration="London-born conscious womenswear with romantic, polished, everyday city pieces.",
        best_city_slugs=("london", "copenhagen", "paris"),
        compatible_city_slugs=("new-york", "los-angeles"),
        weaker_city_slugs=("tokyo",),
        quality_score=8,
        haroona_fit_score=9,
    ),
    "romwe": MerchantProfile(
        merchant_key="romwe",
        display_name="ROMWE",
        source_type="global_fast_fashion",
        brand_vibes=("trend-led", "gen-z", "y2k", "fast-fashion"),
        aspiration="Trend-heavy global fast fashion; useful only when the individual item strongly matches a city mood.",
        best_city_slugs=("new-york", "los-angeles", "tokyo"),
        compatible_city_slugs=("london",),
        weaker_city_slugs=("paris", "copenhagen"),
        quality_score=4,
        haroona_fit_score=5,
    ),
    "rainbow": MerchantProfile(
        merchant_key="rainbow",
        display_name="Rainbow Shops",
        source_type="value_retailer",
        brand_vibes=("affordable", "trend-led", "everyday", "going-out"),
        aspiration="Accessible trend/value fashion; needs stronger product-level filtering for Haroona.",
        best_city_slugs=("new-york", "los-angeles"),
        compatible_city_slugs=("tokyo",),
        weaker_city_slugs=("paris", "copenhagen"),
        quality_score=4,
        haroona_fit_score=5,
    ),
    "lilysilk": MerchantProfile(
        merchant_key="lilysilk",
        display_name="LILYSILK",
        source_type="city_compatible_brand",
        brand_vibes=("silk", "elevated-basics", "minimal", "quiet-luxury"),
        aspiration="Elevated silk basics and polished wardrobe pieces.",
        best_city_slugs=("paris", "london", "new-york"),
        compatible_city_slugs=("copenhagen", "los-angeles"),
        quality_score=8,
        haroona_fit_score=8,
    ),
    "beams": MerchantProfile(
        merchant_key="beams",
        display_name="BEAMS",
        origin_city_slug="tokyo",
        origin_country="Japan",
        source_type="city_based_brand",
        brand_vibes=("tokyo", "streetwear", "heritage", "playful", "design-forward"),
        aspiration="Tokyo-rooted design-forward lifestyle and streetwear.",
        best_city_slugs=("tokyo",),
        compatible_city_slugs=("new-york", "copenhagen"),
        quality_score=8,
        haroona_fit_score=8,
    ),
    "musinsa": MerchantProfile(
        merchant_key="musinsa",
        display_name="MUSINSA",
        origin_city_slug="seoul",
        origin_country="South Korea",
        source_type="city_based_marketplace",
        brand_vibes=("seoul", "streetwear", "minimal", "trend-led"),
        aspiration="Seoul fashion marketplace with strong streetwear and modern casual direction.",
        best_city_slugs=("seoul", "tokyo"),
        compatible_city_slugs=("new-york", "london"),
        quality_score=7,
        haroona_fit_score=7,
    ),
}


MERCHANT_ALIASES: dict[str, str] = {
    "nobody-s-child": "nobodys-child",
    "nobodys-child": "nobodys-child",
    "nobodyschild": "nobodys-child",
    "nobody-child": "nobodys-child",
    "rainbow-shops": "rainbow",
    "rainbowshop": "rainbow",
    "rainbowshops": "rainbow",
}


def normalize_merchant_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.lower().replace("&", "and")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return MERCHANT_ALIASES.get(normalized, normalized)


def get_merchant_profile(merchant_name: str | None) -> MerchantProfile | None:
    return MERCHANT_PROFILES.get(normalize_merchant_key(merchant_name))


def evaluate_merchant_fit(*, merchant_name: str | None, target_city_slug: str) -> MerchantFitResult:
    profile = get_merchant_profile(merchant_name)
    if not profile:
        return MerchantFitResult(
            score_adjustment=0,
            reasons=[],
            city_connection_type=None,
            city_connection_note=None,
            profile=None,
        )

    score_adjustment = 0
    reasons: list[str] = []
    city_connection_type = profile.source_type

    if profile.origin_city_slug and profile.origin_city_slug == target_city_slug:
        score_adjustment += 12
        city_connection_type = "city_based_brand"
        reasons.append(f"merchant origin: {profile.origin_city_slug}")
    elif target_city_slug in profile.best_city_slugs:
        score_adjustment += 9
        reasons.append(f"merchant best-city fit: {target_city_slug}")
    elif target_city_slug in profile.compatible_city_slugs:
        score_adjustment += 4
        reasons.append(f"merchant compatible: {target_city_slug}")
    elif target_city_slug in profile.weaker_city_slugs:
        score_adjustment -= 6
        reasons.append(f"merchant weaker fit: {target_city_slug}")

    if profile.haroona_fit_score >= 8:
        score_adjustment += 5
        reasons.append("merchant Haroona fit: strong")
    elif profile.haroona_fit_score <= 4:
        score_adjustment -= 4
        reasons.append("merchant Haroona fit: weak")

    if profile.quality_score >= 8:
        score_adjustment += 3
        reasons.append("merchant quality signal: strong")
    elif profile.quality_score <= 4:
        score_adjustment -= 2
        reasons.append("merchant quality signal: lower")

    if profile.brand_vibes:
        reasons.append("merchant vibe: " + ", ".join(profile.brand_vibes[:4]))

    city_connection_note = profile.aspiration
    return MerchantFitResult(
        score_adjustment=score_adjustment,
        reasons=reasons,
        city_connection_type=city_connection_type,
        city_connection_note=city_connection_note,
        profile=profile,
    )

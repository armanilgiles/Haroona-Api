from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def read_normalized(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text, newline


def write_preserve(path: Path, text: str, newline: str) -> None:
    path.write_text(text.replace("\n", newline), encoding="utf-8", newline="")


def replace_once(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise RuntimeError(f"Could not find expected block for: {label}")
    return text.replace(old, new, 1), True


def ensure_repo_root() -> None:
    required = [
        ROOT / "app" / "curation" / "scoring.py",
        ROOT / "app" / "curation" / "shopify_collection.py",
        ROOT / "app" / "routers" / "catalog_admin.py",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "Run this from the Haroona-Api repo root. Missing:\n" + "\n".join(missing)
        )


def write_merchant_profiles() -> bool:
    path = ROOT / "app" / "curation" / "merchant_profiles.py"
    content = '''from __future__ import annotations

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
'''
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    newline = "\r\n"
    if path.exists():
        _, newline = read_normalized(path)
    write_preserve(path, content, newline)
    return True


def update_scoring() -> list[str]:
    path = ROOT / "app" / "curation" / "scoring.py"
    text, newline = read_normalized(path)
    changes: list[str] = []

    if "from app.curation.merchant_profiles import evaluate_merchant_fit" not in text:
        text, changed = replace_once(
            text,
            "from dataclasses import dataclass\n\n\n@dataclass",
            "from dataclasses import dataclass\n\nfrom app.curation.merchant_profiles import evaluate_merchant_fit\n\n\n@dataclass",
            "scoring import merchant profile evaluator",
        )
        if changed:
            changes.append("scoring.py: imported merchant profile evaluator")

    if "city_connection_type: str | None = None" not in text:
        text, changed = replace_once(
            text,
            "class ScoreResult:\n    score: int\n    reasons: list[str]\n",
            "class ScoreResult:\n    score: int\n    reasons: list[str]\n    city_connection_type: str | None = None\n    city_connection_note: str | None = None\n",
            "ScoreResult city connection fields",
        )
        if changed:
            changes.append("scoring.py: added city connection fields to ScoreResult")

    if "merchant_name: str | None = None" not in text:
        text, changed = replace_once(
            text,
            "    normalized_category: str | None = None,\n) -> ScoreResult:",
            "    normalized_category: str | None = None,\n    merchant_name: str | None = None,\n) -> ScoreResult:",
            "score_city_fit merchant_name argument",
        )
        if changed:
            changes.append("scoring.py: added merchant_name argument")

    old_brand_block = '''    if "nobody's child" in haystack or "nobodys child" in haystack:
        score += 3
        reasons.append("brand fit")

    score = max(0, min(100, score))
    return ScoreResult(score=score, reasons=reasons[:12])'''
    new_merchant_block = '''    merchant_fit = evaluate_merchant_fit(
        merchant_name=merchant_name,
        target_city_slug=target_city_slug,
    )
    score += merchant_fit.score_adjustment
    reasons.extend(merchant_fit.reasons)

    score = max(0, min(100, score))
    return ScoreResult(
        score=score,
        reasons=reasons[:16],
        city_connection_type=merchant_fit.city_connection_type,
        city_connection_note=merchant_fit.city_connection_note,
    )'''
    if "merchant_fit = evaluate_merchant_fit(" not in text:
        text, changed = replace_once(text, old_brand_block, new_merchant_block, "merchant scoring block")
        if changed:
            changes.append("scoring.py: replaced hardcoded brand bonus with merchant profile scoring")

    write_preserve(path, text, newline)
    return changes


def update_shopify_collection() -> list[str]:
    path = ROOT / "app" / "curation" / "shopify_collection.py"
    text, newline = read_normalized(path)
    changes: list[str] = []

    if "city_connection_type: str | None" not in text:
        text, changed = replace_once(
            text,
            "    normalized_category: str | None\n    target_city_slug: str\n    haroona_score: int",
            "    normalized_category: str | None\n    target_city_slug: str\n    city_connection_type: str | None\n    city_connection_note: str | None\n    haroona_score: int",
            "CandidatePayload city connection fields",
        )
        if changed:
            changes.append("shopify_collection.py: added city connection fields to CandidatePayload")

    score_call_with_merchant = (
        "            target_city_slug=options.target_city_slug,\n"
        "            normalized_category=normalized_category,\n"
        "            merchant_name=options.merchant_name,\n"
        "        )\n\n        review_notes"
    )
    if score_call_with_merchant not in text:
        text, changed = replace_once(
            text,
            "            target_city_slug=options.target_city_slug,\n            normalized_category=normalized_category,\n        )\n\n        review_notes",
            "            target_city_slug=options.target_city_slug,\n            normalized_category=normalized_category,\n            merchant_name=options.merchant_name,\n        )\n\n        review_notes",
            "pass merchant_name into score_city_fit",
        )
        if changed:
            changes.append("shopify_collection.py: passes merchant_name into scoring")

    if "city_connection_type=score.city_connection_type" not in text:
        text, changed = replace_once(
            text,
            "                normalized_category=normalized_category,\n                target_city_slug=options.target_city_slug,\n                haroona_score=score.score,",
            "                normalized_category=normalized_category,\n                target_city_slug=options.target_city_slug,\n                city_connection_type=score.city_connection_type,\n                city_connection_note=score.city_connection_note,\n                haroona_score=score.score,",
            "save score city connection into payload",
        )
        if changed:
            changes.append("shopify_collection.py: adds score city connection to payload")

    if "record.city_connection_type = payload.city_connection_type" not in text:
        text, changed = replace_once(
            text,
            "        record.normalized_category = payload.normalized_category\n        record.target_city_slug = payload.target_city_slug\n        record.haroona_score = payload.haroona_score",
            "        record.normalized_category = payload.normalized_category\n        record.target_city_slug = payload.target_city_slug\n        record.city_connection_type = payload.city_connection_type\n        record.city_connection_note = payload.city_connection_note\n        record.haroona_score = payload.haroona_score",
            "persist city connection fields",
        )
        if changed:
            changes.append("shopify_collection.py: persists city connection fields")

    if '"city_connection_type": item.city_connection_type' not in text:
        text, changed = replace_once(
            text,
            '                "normalized_category": item.normalized_category,\n                "haroona_score": item.haroona_score,',
            '                "normalized_category": item.normalized_category,\n                "city_connection_type": item.city_connection_type,\n                "city_connection_note": item.city_connection_note,\n                "haroona_score": item.haroona_score,',
            "return city connection fields from scan result",
        )
        if changed:
            changes.append("shopify_collection.py: returns city connection fields in scan response")

    write_preserve(path, text, newline)
    return changes


def update_catalog_admin() -> list[str]:
    path = ROOT / "app" / "routers" / "catalog_admin.py"
    text, newline = read_normalized(path)
    changes: list[str] = []

    if '"city_connection_type": row.city_connection_type' not in text:
        text, changed = replace_once(
            text,
            '                "target_city_slug": row.target_city_slug,\n                "haroona_score": row.haroona_score,',
            '                "target_city_slug": row.target_city_slug,\n                "city_connection_type": row.city_connection_type,\n                "city_connection_note": row.city_connection_note,\n                "haroona_score": row.haroona_score,',
            "product candidate API city connection fields",
        )
        if changed:
            changes.append("catalog_admin.py: returns city connection fields in product candidate API")

    write_preserve(path, text, newline)
    return changes


def main() -> None:
    ensure_repo_root()
    changes: list[str] = []

    if write_merchant_profiles():
        changes.append("merchant_profiles.py: created/updated merchant profile config")

    changes.extend(update_scoring())
    changes.extend(update_shopify_collection())
    changes.extend(update_catalog_admin())

    print("Merchant profile scoring update complete.")
    if changes:
        print("Changed:")
        for change in changes:
            print(f"- {change}")
    else:
        print("No file changes were needed; it looks already applied.")


if __name__ == "__main__":
    main()

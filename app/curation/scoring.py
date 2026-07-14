from __future__ import annotations

from dataclasses import dataclass

from app.curation.merchant_profiles import evaluate_merchant_fit


@dataclass(frozen=True)
class ScoreResult:
    score: int
    reasons: list[str]
    city_connection_type: str | None = None
    city_connection_note: str | None = None


CITY_RULES: dict[str, dict[str, list[str]]] = {
    "new-york": {
        "positive": [
            "black", "satin", "silk", "slip", "bodycon", "mini", "midi", "tailored",
            "blazer", "sleek", "evening", "party", "night", "lace", "mesh", "leather",
            "structured", "halter", "strapless",
        ],
        "negative": ["beach", "vacation", "bikini", "cover up", "country"],
    },
    "london": {
        "positive": [
            "midi", "maxi", "tea dress", "cotton", "linen", "blend", "shirt dress",
            "skirt", "trouser", "tailored", "stripe", "polka", "floral", "black",
            "green", "cream", "natural", "volume", "smock", "shirring", "detail",
        ],
        "negative": ["bodycon", "club", "neon", "micro", "bikini"],
    },
    "paris": {
        "positive": [
            "midi", "maxi", "black", "cream", "white", "navy", "stripe", "tailored",
            "linen", "cotton", "shirt", "blouse", "skirt", "minimal", "polka", "wrap",
        ],
        "negative": ["logo", "neon", "club", "micro", "bodycon"],
    },
    "copenhagen": {
        "positive": [
            "cotton", "organic", "linen", "blend", "natural", "green", "cream", "volume",
            "oversized", "smock", "stripe", "co-ord", "skirt", "trouser", "relaxed",
        ],
        "negative": ["club", "bodycon", "neon", "micro"],
    },
    "los-angeles": {
        "positive": [
            "summer", "cotton", "linen", "mini", "maxi", "halter", "strapless", "sun",
            "vacation", "denim", "cream", "white", "pink", "floral", "relaxed",
        ],
        "negative": ["heavy", "wool", "winter", "coat"],
    },
    "tokyo": {
        "positive": [
            "layer", "oversized", "mini", "volume", "print", "stripe", "bow", "cute",
            "statement", "co-ord", "skirt", "playful", "puff", "smock",
        ],
        "negative": ["basic", "plain"],
    },
}


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "dress": ["dress", "gown"],
    "dresses": ["dress", "gown"],
    "tops": ["top", "blouse", "shirt", "camisole", "vest", "tee"],
    "skirt": ["skirt"],
    "skirts": ["skirt"],
    "bottoms": ["trouser", "pant", "jean", "skirt", "short"],
    "co-ords": ["co-ord", "co ord", "set"],
    "shoes": ["shoe", "sandal", "boot", "heel", "sneaker"],
    "bags": ["bag", "purse", "tote"],
    "accessories": ["accessory", "scarf", "belt", "hat", "sunglasses"],
    "jewelry": ["necklace", "earring", "bracelet", "ring", "jewellery", "jewelry"],
}


def _contains(haystack: str, keyword: str) -> bool:
    return keyword.lower() in haystack


def score_city_fit(
    *,
    title: str,
    description: str | None = None,
    product_type: str | None = None,
    tags: list[str] | None = None,
    target_city_slug: str = "london",
    normalized_category: str | None = None,
    merchant_name: str | None = None,
) -> ScoreResult:
    """Simple deterministic Haroona-fit score.

    This is intentionally not AI yet. It gives Curate Studio a cheap first pass
    so the queue starts with likely-good items instead of every scraped product.
    """
    haystack = " ".join(
        [
            title or "",
            description or "",
            product_type or "",
            " ".join(tags or []),
        ]
    ).lower()

    rules = CITY_RULES.get(target_city_slug, CITY_RULES["london"])
    score = 50
    reasons: list[str] = []

    for keyword in rules["positive"]:
        if _contains(haystack, keyword):
            score += 6
            reasons.append(f"+ {keyword}")

    for keyword in rules["negative"]:
        if _contains(haystack, keyword):
            score -= 8
            reasons.append(f"- {keyword}")

    if normalized_category:
        category_hits = CATEGORY_KEYWORDS.get(normalized_category, [])
        if any(_contains(haystack, keyword) for keyword in category_hits):
            score += 8
            reasons.append(f"category match: {normalized_category}")

    merchant_fit = evaluate_merchant_fit(
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
    )

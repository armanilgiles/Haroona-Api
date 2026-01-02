import re
from typing import Tuple

ALIASES = {
    "adidas originals": "adidas",
    "nike inc": "nike",
    "nike sportswear": "nike",
}


def normalize_brand(name: str) -> Tuple[str, str]:
    """
    Returns:
      (normalized_brand_key, confidence)
    confidence: exact | alias | fuzzy
    """

    if not name:
        return "", "exact"

    original = name

    value = name.lower().strip()
    value = re.sub(r"[®™©]", "", value)
    value = re.sub(r"[^a-z0-9\s]", "", value)
    value = re.sub(r"\s+", " ", value)

    # Alias match
    if value in ALIASES:
        return ALIASES[value], "alias"

    # Exact match (fallback assumption)
    return value, "exact"

import re
from typing import Tuple

ALIASES = {
    "adidas originals": "adidas",
    "nike inc": "nike",
    "nike sportswear": "nike",
}


def normalize_brand(label: str):
    value = (label or "").strip().lower()

    aliases = {
        "mure + grand": "mure_and_grand",
        "mure & grand": "mure_and_grand",
        "mulberry + grand": "mulberry_and_grand",
        "mulberry & grand": "mulberry_and_grand",
        "patches + pins": "patches_and_pins",
        "patches & pins": "patches_and_pins",
        "dipped shop": "dipped_shop",
        "urban expressions": "urban_expressions",
        "shiraleah": "shiraleah",
        "nike": "nike",
        "adidas": "adidas",
    }

    if value in aliases:
        return aliases[value], 1.0

    fallback = (
        value.replace("&", "and")
        .replace("+", "and")
        .replace(" ", "_")
    )
    return fallback, 0.6

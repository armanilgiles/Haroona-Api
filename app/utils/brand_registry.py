from __future__ import annotations

import re
from typing import Optional


def _norm_key(value: str) -> str:
    v = value.strip().lower()
    v = re.sub(r"[^a-z0-9]+", "", v)
    return v


LOGO_BY_KEY: dict[str, str] = {
    "macys": "/logos/macys.png",
    "nordstrom": "/logos/nordstrom.png",
    "zara": "/logos/zara.png",
    "hm": "/logos/hm.png",
    "uniqlo": "/logos/uniqlo.png",
    "asos": "/logos/asos.png",
    "nike": "/logos/nike.png",
    "adidas": "/logos/adidas.png",
}


def lookup_logo_url(*, brand_name: str | None, advertiser_id: str | None) -> Optional[str]:
    if advertiser_id:
        key = _norm_key(advertiser_id)
        if key in LOGO_BY_KEY:
            return LOGO_BY_KEY[key]

    if brand_name:
        key = _norm_key(brand_name)
        if key in LOGO_BY_KEY:
            return LOGO_BY_KEY[key]

    return None
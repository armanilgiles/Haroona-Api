from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ManualProductSeed:
    key: str

    source: str
    source_file: str
    advertiser_id: str

    brand_name: str
    brand_logo_url: str | None

    country_code: str
    country_name: str

    city_slug: str
    city_name: str
    latitude: Decimal
    longitude: Decimal
    marker_color: str | None

    review_notes: str | None
    products: Sequence[Mapping[str, Any]]

    currency: str = "USD"
    default_availability: str = "in_stock"

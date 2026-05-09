from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = "awin"
SOURCE_FILE = "manual-awin-nexbie-la"
ADVERTISER_ID = "125854"
BRAND_NAME = "Nexbie"
BRAND_LOGO_URL = None

AFFILIATE_URL = "https://www.awin1.com/cread.php?awinmid=125854&awinaffid=2843918&clickref=haroona_la_aeroraise_card&ued=https%3A%2F%2Fshoes.nexbie.com%2Fproducts%2Faeroraise-3d-printed-sneakers%3Fvariant%3D48057165381851"
MERCHANT_URL = "https://shoes.nexbie.com/products/aeroraise-3d-printed-sneakers?variant=48057165381851"

PRODUCTS = [
    {
        "external_id": "nexbie-aeroraise-3d-printed-sneakers-orange-48057165381851",
        "sku": "48057165381851",
        "name": "Aeroraise 3D Printed Sneakers",
        "description": "Bright orange 3D-printed sneakers selected as a tech-active LA lifestyle pick.",
        "price": Decimal("159.00"),
        "regular_price": Decimal("269.99"),
        "affiliate_url": AFFILIATE_URL,
        "merchant_url": MERCHANT_URL,
        "image_url": "https://shoes.nexbie.com/cdn/shop/files/orange-3d-printed-sneakers.webp?v=1777431698&width=1080",
        "category": "shoes",
        "style": "LA tech-active lifestyle",
        "vibe": "futuristic active",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for LA’s tech-active lifestyle",
        "city_connection_note": "Selected for a futuristic, lightweight sneaker look that fits LA’s active city-to-outdoor rhythm.",
    },
]

SEED = ManualProductSeed(
    key="nexbie_la",
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code="US",
    country_name="United States",
    city_slug="los-angeles",
    city_name="Los Angeles",
    latitude=Decimal("34.052235"),
    longitude=Decimal("-118.243683"),
    marker_color="#F4A261",
    review_notes="Manually curated Awin/Nexbie Los Angeles city-inspired shoe product.",
    products=PRODUCTS,
)

from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = "manual"
SOURCE_FILE = "manual-bridge-and-burn-nyc"
ADVERTISER_ID = "bridgeandburn"
BRAND_NAME = "Bridge & Burn"
BRAND_LOGO_URL = None

PRODUCTS = [
    {
        "external_id": "bridge-and-burn-innes-shirt-black",
        "sku": "innes-shirt-black",
        "name": "The Innes Shirt / Black",
        "price": Decimal("118.00"),
        "regular_price": Decimal("118.00"),
        "affiliate_url": "https://www.bridgeandburn.com/products/innes-shirt-black?ktk=MDFXc0RPLTlkZDY5MmE5N2Y4",
        "merchant_url": "https://www.bridgeandburn.com/products/innes-shirt-black",
        "image_url": "https://www.bridgeandburn.com/cdn/shop/files/Bridgeburn68f7ee235571f268f7ee23558ab.4616864568f7ee23558ab_1800x1800.jpg?v=1775750671",
        "image_alt": "The Bridge & Burn Innes Shirt in black, a relaxed short-sleeve button-up blouse.",
        "category": "tops",
        "style": "NYC black button-up",
        "vibe": "clean city casual",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the NYC black button-up look",
        "city_connection_note": "Selected because the black relaxed button-up feels clean, versatile, and easy to style for a New York city-casual look.",
    },
]

SEED = ManualProductSeed(
    key="bridge_and_burn_nyc",
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code="US",
    country_name="United States",
    city_slug="new-york",
    city_name="New York",
    latitude=Decimal("40.712776"),
    longitude=Decimal("-74.005974"),
    marker_color="#1D3557",
    review_notes="Manually curated Bridge & Burn NYC city-inspired product.",
    products=PRODUCTS,
)

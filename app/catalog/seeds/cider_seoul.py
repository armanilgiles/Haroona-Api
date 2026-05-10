from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = "sovrn"
SOURCE_FILE = "manual-sovrn-cider-seoul"
ADVERTISER_ID = "shopcider"
BRAND_NAME = "Cider"
BRAND_LOGO_URL = None

AFFILIATE_URL = "https://sovrn.co/64f3iv0"
MERCHANT_URL = "https://www.shopcider.com/goods/cotton-v-neck-broderie-anglaise-pleated-shirred-short-sleeve-blouse-114745091?style_id=2179670"

PRODUCTS = [
    {
        "external_id": "cider-114745091-cotton-v-neck-broderie-anglaise-blouse-white-2179670",
        "sku": "114745091-2179670",
        "name": "Cotton V-neck Broderie Anglaise Pleated Shirred Short Sleeve Blouse",
        "description": "A white cotton broderie anglaise blouse with a soft V-neck, pleated shirring, and short sleeves selected for Seoul-inspired styling.",
        "price": Decimal("34.90"),
        "regular_price": Decimal("34.90"),
        "affiliate_url": AFFILIATE_URL,
        "merchant_url": MERCHANT_URL,
        "image_url": "https://bcdn-images.hotdata.cc/images/products/CIDER-Cotton-V-neck-Broderie-Anglaise-Pleated-Shirred-Short-Sleeve-Blouse-12448edc620406c4.jpg?width=3840",
        "category": "tops",
        "style": "Seoul soft blouse",
        "vibe": "soft feminine",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Seoul · City-inspired pick",
        "city_connection_note": "Selected for its soft white blouse silhouette, delicate broderie texture, and feminine styling fit for Seoul-inspired discovery.",
    },
]

SEED = ManualProductSeed(
    key="cider_seoul",
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code="KR",
    country_name="South Korea",
    city_slug="seoul",
    city_name="Seoul",
    latitude=Decimal("37.566535"),
    longitude=Decimal("126.977969"),
    marker_color="#7C3AED",
    review_notes="Manually curated Sovrn/Cider Seoul city-inspired blouse product. Sovrn approval may still be pending.",
    products=PRODUCTS,
)

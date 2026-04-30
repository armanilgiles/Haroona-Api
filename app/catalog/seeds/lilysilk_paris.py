from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = "manual"
SOURCE_FILE = "manual-lilysilk-paris"
ADVERTISER_ID = "lilysilk"
BRAND_NAME = "LILYSILK"
BRAND_LOGO_URL = None

PRODUCTS = [
    {
        "external_id": "lilysilk-10033a-cowl-neck-watershine-silk-midi-dress",
        "sku": "10033A",
        "name": "Cowl-Neck Watershine Silk Midi Dress",
        "price": Decimal("179.00"),
        "regular_price": Decimal("279.00"),
        "affiliate_url": None,
        "merchant_url": "https://www.lilysilk.com/us/product/cowl-neck-watershine-silk-midi-dress.html",
        "image_url": "https://img.lilysilk.com/cdn-cgi/image/width=1800,height=2700,quality=80,fit=cover/media/catalog/product/m2_custom/10033A/355BR/1.jpg",
        "video_url": "https://images.lilysilk.com/promotion/product/video/gallery/10033A.mp4",
        "category": "dress",
        "style": "Paris silk minimal",
        "vibe": "quiet luxury",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the Paris silk look",
        "city_connection_note": "Selected because it captures the soft, minimal elegance associated with Paris style.",
    },
    {
        "external_id": "lilysilk-elegant-alluring-cowl-neck-silk-dress",
        "sku": "N9452",
        "name": "Elegant Alluring Cowl Neck Silk Dress",
        "price": Decimal("83.00"),
        "regular_price": Decimal("280.00"),
        "affiliate_url": None,
        "merchant_url": "https://www.lilysilk.com/us/product/elegant-alluring-cowl-neck-silk-slip-dress.html",
        "image_url": "https://img.lilysilk.com/cdn-cgi/image/width=1800,height=2700,quality=80,fit=cover/media/catalog/product/N9452/252/1.jpg",
        "video_url": None,
        "category": "dress",
        "style": "Paris silk evening",
        "vibe": "quiet luxury",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the Paris evening look",
        "city_connection_note": "Selected because the silk slip silhouette fits a quiet, polished Paris evening mood.",
    },
]

SEED = ManualProductSeed(
    key="lilysilk_paris",
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code="FR",
    country_name="France",
    city_slug="paris",
    city_name="Paris",
    latitude=Decimal("48.856600"),
    longitude=Decimal("2.352200"),
    marker_color="#C9B79C",
    review_notes="Manually curated non-affiliate LILYSILK Paris products.",
    products=PRODUCTS,
)

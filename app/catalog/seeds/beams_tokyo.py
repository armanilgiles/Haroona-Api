from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = "manual"
SOURCE_FILE = "manual-beams-tokyo"
ADVERTISER_ID = "beams-america"
BRAND_NAME = "Ray BEAMS"
BRAND_LOGO_URL = None

PRODUCTS = [   
    {
        "external_id": "beams-6104133537019-2-way-convertible-velour-camisole-black",
        "sku": "61-04-1335-370-19",
        "name": "2-Way Convertible Velour Camisole",
        "description": "A soft black velour camisole with removable straps for camisole or bandeau styling.",
        "price": Decimal("105.00"),
        "regular_price": Decimal("105.00"),
        "affiliate_url": None,
        "merchant_url": "https://beams-america.com/products/6104133537075",
        "image_url": "https://beams-america.com/cdn/shop/files/178b1824f76e11f0a8b90242ac110005.jpg?v=1776805538&width=1100",
        "category": "tops",
        "style": "Tokyo layered minimal",
        "vibe": "soft city night",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "Tokyo · City-based brand",
        "city_connection_note": "From Ray BEAMS, a BEAMS women’s line connected to Tokyo-rooted Japanese city style and relaxed layering.",
    },
    {
        "external_id": "beams-6111088337019-dot-crinkle-ruffle-shirt-black",
        "sku": "61-11-0883-370-19",
        "name": "Dot Crinkle Ruffle Shirt",
        "description": "A lightweight black polka-dot shirt with crinkle texture and soft ruffle detailing.",
        "price": Decimal("155.00"),
        "regular_price": Decimal("155.00"),
        "affiliate_url": None,
        "merchant_url": "https://beams-america.com/products/6111088337019",
        "image_url": "https://beams-america.com/cdn/shop/files/IMG_05908.webp?v=1774647636&width=1100",
        "category": "tops",
        "style": "Tokyo playful blouse",
        "vibe": "soft statement",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "Tokyo · City-based brand",
        "city_connection_note": "From Ray BEAMS, selected for Tokyo’s playful, layered, slightly feminine street-prep styling.",
    },
    {
        "external_id": "beams-6105047037052-versatile-multi-stripe-knit-camisole-yellow",
        "sku": "61-05-0470-370-52",
        "name": "Versatile Multi-Stripe Knit Camisole",
        "description": "A textured yellow multi-stripe knit camisole with detachable straps for layered Tokyo styling.",
        "price": Decimal("130.00"),
        "regular_price": Decimal("130.00"),
        "affiliate_url": None,
        "merchant_url": "https://beams-america.com/products/6105047037052",
        "image_url": "https://beams-america.com/cdn/shop/files/14e21292c90311f09f9f0242ac110006.jpg?v=1776799374",
        "category": "tops",
        "style": "Tokyo playful layering",
        "vibe": "bright textured stripe",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "Tokyo · City-based brand",
        "city_connection_note": "From Ray BEAMS, selected for the compact striped knit silhouette and playful layering that fits Tokyo street-prep styling.",
    },
    {
        "external_id": "beams-6123135046219-stretch-capri-pants-black",
        "sku": "61-23-1350-462-19",
        "name": "Stretch Capri Pants",
        "description": "Clean black stretch capri pants with a slim, polished silhouette for everyday city styling.",
        "price": Decimal("165.00"),
        "regular_price": Decimal("165.00"),
        "affiliate_url": None,
        "merchant_url": "https://beams-america.com/products/6123135046219",
        "image_url": "https://beams-america.com/cdn/shop/files/acdff368cc3011f090d70242ac110005.jpg?v=1776799434&width=1107",
        "category": "bottoms",
        "style": "Tokyo clean street",
        "vibe": "polished casual",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "Tokyo · City-based brand",
        "city_connection_note": "From Ray BEAMS, selected for a clean, slim city silhouette that supports Tokyo-inspired outfit building.",
    },
]

SEED = ManualProductSeed(
    key="beams_tokyo",
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code="JP",
    country_name="Japan",
    city_slug="tokyo",
    city_name="Tokyo",
    latitude=Decimal("35.676400"),
    longitude=Decimal("139.650000"),
    marker_color="#E76F51",
    review_notes="Manually curated non-affiliate Ray BEAMS Tokyo products for catalog volume.",
    products=PRODUCTS,
)

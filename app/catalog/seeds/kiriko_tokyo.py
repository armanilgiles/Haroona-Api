from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'manual'
SOURCE_FILE = 'manual-kiriko-tokyo'
ADVERTISER_ID = 'kiriko-made'
BRAND_NAME = 'Kiriko Made'
BRAND_LOGO_URL = None

PRODUCTS = [
    {
        "external_id": "kiriko-original-v-neck-tunic-sunflower-chijimi",
        "sku": "KTOK01",
        "name": "Kiriko x ToK, V-Neck Tunic, Sunflower Chijimi",
        "price": Decimal("98.00"),
        "regular_price": Decimal("98.00"),
        "affiliate_url": "https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi",
        "merchant_url": "https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi",
        "image_url": "https://kirikomade.com/cdn/shop/files/DYL_8718_720x.png?v=1748454979",
        "category": "tops",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "availability": "out_of_stock",
        "is_active": True,
"city_connection_type": "local_boutique",
"city_connection_location": "Tokyo · Local boutique",
        "city_connection_note": "Selected because it reflects the quiet, artisan feel of Tokyo-inspired casual style.",
    },
    {
        "external_id": "shijira-pants-indigo-small-grid",
        "name": "ToK Pants, Chijimi Indigo with Small Grid",
        "price": Decimal("68.00"),
        "regular_price": Decimal("68.00"),
        "affiliate_url": "https://kirikomade.com/products/shijira-pants-indigo-small-grid?ktk=MDFXc0RPLTA0ZTAyMWEwOTNh",
        "merchant_url": "https://kirikomade.com/products/shijira-pants-indigo-small-grid",
        "image_url": "https://kirikomade.com/cdn/shop/products/model_10_1_2048x.jpg?v=1684495207",
        "category": "pants",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "city_connection_type": "local_boutique",
        "city_connection_location": "Tokyo · Local boutique",
"city_connection_note": "From a local Tokyo boutique with a quiet, artisan approach to heritage-inspired style.",    },
    {
        "external_id": "kiriko-original-patched-lee-shirt-dress-cream",
        "name": "Kiriko Custom Patched Lee Shirt Dress, Cream",
        "price": Decimal("278.00"),
        "regular_price": Decimal("278.00"),
        "affiliate_url": "https://kirikomade.com/products/kiriko-original-patched-lee-shirt-dress-cream?ktk=MDFXc0RPLWZlMTBlZDM2MGJl",
        "merchant_url": "https://kirikomade.com/products/kiriko-original-patched-lee-shirt-dress-cream",
        "image_url": "https://kirikomade.com/cdn/shop/files/DYL_7248_2048x.png?v=1758911935",
        "category": "dress",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "city_connection_type": "local_boutique",
        "city_connection_location": "Tokyo · Local boutique",
"city_connection_note": "From a local Tokyo boutique with a quiet, artisan approach to heritage-inspired style.",    },
    {
        "external_id": "kiriko-original-pants-black-and-chartcoal-patched-wide-leg",
        "name": "Kiriko Custom Pants, Black and Charcoal Patched, Wide Leg",
        "price": Decimal("148.00"),
        "regular_price": Decimal("148.00"),
        "affiliate_url": "https://kirikomade.com/products/kiriko-original-pants-black-and-chartcoal-patched-wide-leg?ktk=MDFXc0RPLTlkNDFhYTQ3M2Q3",
        "merchant_url": "https://kirikomade.com/products/kiriko-original-pants-black-and-chartcoal-patched-wide-leg",
        "image_url": "https://kirikomade.com/cdn/shop/files/DYL_1998_a1af6f83-5a2a-407e-95a5-f49ae507798c_2048x.png?v=1760125343",
        "category": "pants",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "city_connection_type": "local_boutique",
        "city_connection_location": "Tokyo · Local boutique",
"city_connection_note": "From a local Tokyo boutique with a quiet, artisan approach to heritage-inspired style.",    },
    {
        "external_id": "oversized-a-line-pocket-dress-skinny-blue-weave-with-front-button",
        "name": "ToK Pocket Dress, Oversized A-Line, Front Button, Chijimi, Grid",
        "price": Decimal("95.00"),
        "regular_price": Decimal("95.00"),
        "affiliate_url": "https://kirikomade.com/products/oversized-a-line-pocket-dress-skinny-blue-weave-with-front-button?ktk=MDFXc0RPLTQ2ZTU4MTZiMjFm",
        "merchant_url": "https://kirikomade.com/products/oversized-a-line-pocket-dress-skinny-blue-weave-with-front-button",
        "image_url": "https://kirikomade.com/cdn/shop/products/model_1_1_9e3a5800-d91b-49ae-8544-c123077d2fbd_2048x.jpg?v=1684494230",
        "category": "dress",
        "style": "Tokyo heritage casual",
        "vibe": "quiet artisan",
        "is_best_seller": False,
        "city_connection_type": "local_boutique",
        "city_connection_location": "Tokyo · Local boutique",
"city_connection_note": "From a local Tokyo boutique with a quiet, artisan approach to heritage-inspired style.",    },
]
SEED = ManualProductSeed(
    key='kiriko_tokyo',
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code='JP',
    country_name='Japan',
    city_slug='tokyo',
    city_name='Tokyo',
    latitude=Decimal('35.676400'),
    longitude=Decimal('139.650000'),
    marker_color='#E76F51',
    review_notes='Manually curated Kiriko Made Tokyo products.',
    products=PRODUCTS,
)

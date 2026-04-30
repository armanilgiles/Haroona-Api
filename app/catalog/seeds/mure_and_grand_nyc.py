from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'awin'
SOURCE_FILE = 'manual-awin-mure-and-grand-nyc'
ADVERTISER_ID = '90981'
BRAND_NAME = 'Mure + Grand'
BRAND_LOGO_URL = None

PRODUCTS = [
    {
        "external_id": "one-shoulder-ribbed-crop-top",
        "sku": "one-shoulder-ribbed-crop-top",
        "name": "Tai One Strap Ribbed Seamless Top",
        "price": Decimal("30.00"),
        "regular_price": Decimal("30.00"),
        "affiliate_url": "https://www.awin1.com/cread.php?awinmid=90981&awinaffid=2843918&ued=https%3A%2F%2Fmureandgrand.com%2Fproducts%2Fone-shoulder-ribbed-crop-top",
        "merchant_url": "https://mureandgrand.com/products/one-shoulder-ribbed-crop-top",
        "image_url": "https://cdn.shopify.com/s/files/1/0735/4893/products/tai-one-shoulder-ribbed-seamless-top-top-mure-grand-black-813557.jpg?v=1697938537",
        "category": "tops",
        "style": "NYC fitted casual",
        "vibe": "sleek sporty",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "local_boutique",
        "city_connection_location": "New York · Local boutique",
        "city_connection_note": "From a local New York boutique with a sleek, playful city style.",
    },
    {
        "external_id": "sadie-tiered-skort-set",
        "sku": "sadie-tiered-skort-set",
        "name": "Sadie Tiered Skort Set",
        "price": Decimal("82.00"),
        "regular_price": Decimal("82.00"),
        "affiliate_url": "https://www.awin1.com/cread.php?awinmid=90981&awinaffid=2843918&ued=https%3A%2F%2Fmureandgrand.com%2Fproducts%2Fsadie-tiered-skort-set",
        "merchant_url": "https://mureandgrand.com/products/sadie-tiered-skort-set",
        "image_url": "https://cdn.shopify.com/s/files/1/0735/4893/files/sadie-tiered-skort-set-clothing-mure-grand-760239.jpg?v=1774379947",
        "category": "set",
        "style": "NYC summer feminine",
        "vibe": "playful polished",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "local_boutique",
        "city_connection_location": "New York · Local boutique",
        "city_connection_note": "From a local New York boutique with a playful, polished summer feel.",
    },
    {
        "external_id": "eliana-flowy-tank-top",
        "sku": "eliana-flowy-tank-top",
        "name": "Eliana Flowy Tank Top",
        "price": Decimal("38.00"),
        "regular_price": Decimal("38.00"),
        "affiliate_url": "https://www.awin1.com/cread.php?awinmid=90981&awinaffid=2843918&ued=https%3A%2F%2Fmureandgrand.com%2Fproducts%2Feliana-flowy-tank-top",
        "merchant_url": "https://mureandgrand.com/products/eliana-flowy-tank-top",
        "image_url": "https://cdn.shopify.com/s/files/1/0735/4893/files/eliana-flowy-tank-top-clothing-mure-grand-372449.jpg?v=1774662239",
        "category": "tops",
        "style": "NYC airy casual",
        "vibe": "soft everyday",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "local_boutique",
        "city_connection_location": "New York · Local boutique",
        "city_connection_note": "From a local New York boutique with an easy, soft everyday city mood.",
    },
    {
        "external_id": "leah-crop-top",
        "sku": "leah-crop-top",
        "name": "Leah Crop Top",
        "price": Decimal("38.00"),
        "regular_price": Decimal("38.00"),
        "affiliate_url": "https://www.awin1.com/cread.php?awinmid=90981&awinaffid=2843918&ued=https%3A%2F%2Fmureandgrand.com%2Fproducts%2Fleah-crop-top",
        "merchant_url": "https://mureandgrand.com/products/leah-crop-top",
        "image_url": "https://cdn.shopify.com/s/files/1/0735/4893/files/leah-crop-top-clothing-mure-grand-lavender-sm-149398.jpg?v=1775069148",
        "category": "tops",
        "style": "NYC fitted feminine",
        "vibe": "clean flirty",
        "is_best_seller": True,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "local_boutique",
        "city_connection_location": "New York · Local boutique",
        "city_connection_note": "From a local New York boutique with a clean, flirty city look.",
    },
]
SEED = ManualProductSeed(
    key='mure_and_grand_nyc',
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code='US',
    country_name='United States',
    city_slug='new-york',
    city_name='New York',
    latitude=Decimal('40.712776'),
    longitude=Decimal('-74.005974'),
    marker_color='#D97706',
    review_notes='Manually curated Mure + Grand NYC products.',
    products=PRODUCTS,
)

from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'cj'
SOURCE_FILE = 'manual-cj-rainbow-nyc'
ADVERTISER_ID = '12398826'
BRAND_NAME = 'Rainbow Shops'
BRAND_LOGO_URL = 'https://cdn.brandfetch.io/idhZZX-Z_I/w/209/h/75/theme/dark/logo.png?c=1dxbfHSJFAPEGdCLU4o5B'

PRODUCTS = [
    {
        "external_id": "rainbow-dress-1",
        "sku": "rainbow-dress-1",
        "name": "Black Ponte Halter Mini Skater Dress",
        "price": Decimal("19.99"),
        "regular_price": Decimal("29.99"),
        "affiliate_url": "https://www.tkqlhce.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/black-ponte-halter-mini-skater-dress-1094077667002",
        "merchant_url": "https://www.rainbowshops.com/products/black-ponte-halter-mini-skater-dress-1094077667002",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/1094077667002001_001.jpg?v=1776811499&width=1300",
        "category": "dress",
        "style": "NYC night",
        "vibe": "edgy nightlife",
        "is_best_seller": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "New York-rooted brand",
        "city_connection_note": "From a New York-rooted retailer with bold, affordable city-night style.",
    },
    {
        "external_id": "rainbow-jeans-1",
        "sku": "rainbow-jeans-1",
        "name": "Light Wash High Waisted Straight Leg Jeans",
        "price": Decimal("24.99"),
        "regular_price": Decimal("34.99"),
        "affiliate_url": "https://www.anrdoezrs.net/click-101726370-12398826?url=https://www.rainbowshops.com/products/light-wash-high-waisted-whiskered-straight-leg-jeans-3074071618630",
        "merchant_url": "https://www.rainbowshops.com/products/light-wash-high-waisted-whiskered-straight-leg-jeans-3074071618630",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/3074071618630402_001.jpg?v=1776769580&width=1300",
        "category": "bottoms",
        "style": "NYC casual",
        "vibe": "city everyday",
        "is_best_seller": False,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "New York-rooted brand",
        "city_connection_note": "From a New York-rooted retailer with easy everyday city style.",
    },
    {
        "external_id": "rainbow-skirt-1",
        "sku": "rainbow-skirt-1",
        "name": "Wine Faux Leather Mini Pencil Skirt",
        "price": Decimal("19.99"),
        "regular_price": Decimal("29.99"),
        "affiliate_url": "https://www.tkqlhce.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/wine-faux-leather-mini-pencil-skirt-3406068512527",
        "merchant_url": "https://www.rainbowshops.com/products/wine-faux-leather-mini-pencil-skirt-3406068512527",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/3406068512527061_001_bd23e0c1-d1ab-4cd5-976d-78ec65215946.jpg?v=1776783054&width=1300",
        "video_url": "https://www.rainbowshops.com/cdn/shop/videos/c/vp/d75316222d1146d8b56b7577ee9e763a/d75316222d1146d8b56b7577ee9e763a.HD-1080p-7.2Mbps-64589935.mp4?v=0",
        "category": "bottoms",
        "style": "NYC night",
        "vibe": "edgy",
        "is_best_seller": True,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "New York-rooted brand",
        "city_connection_note": "From a New York-rooted retailer with a bold, edgy nightlife mood.",
    },
    {
        "external_id": "rainbow-top-1",
        "sku": "rainbow-top-1",
        "name": "Black Ruched Side Buckle Strap Halter Top",
        "price": Decimal("14.99"),
        "regular_price": Decimal("19.99"),
        "affiliate_url": "https://www.jdoqocy.com/click-101726370-12398826?url=https://www.rainbowshops.com/products/black-ruched-side-buckle-strap-halter-top-1402069393331",
        "merchant_url": "https://www.rainbowshops.com/products/black-ruched-side-buckle-strap-halter-top-1402069393331",
        "image_url": "https://www.rainbowshops.com/cdn/shop/files/1402069393331001_001_31581fbe-3376-420f-a5d2-604bfca37548.jpg?v=1776806219&width=1300",
        "category": "tops",
        "style": "NYC street",
        "vibe": "confident",
        "is_best_seller": False,
        "city_connection_type": "city_based_brand",
        "city_connection_location": "New York-rooted brand",
        "city_connection_note": "From a New York-rooted retailer with confident, street-ready city style.",
    },
]

SEED = ManualProductSeed(
    key='rainbow_nyc',
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code='US',
    country_name='United States',
    city_slug='new-york',
    city_name='New York',
    latitude=Decimal('40.7128'),
    longitude=Decimal('-74.0060'),
    marker_color='#1D3557',
    review_notes='Manually curated CJ/Rainbow Shops NYC products.',
    products=PRODUCTS,
)

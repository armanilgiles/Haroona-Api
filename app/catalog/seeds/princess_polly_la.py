from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'rakuten'
SOURCE_FILE = 'manual-rakuten-princess-polly-la'
ADVERTISER_ID = '1557116'
BRAND_NAME = 'Princess Polly'
BRAND_LOGO_URL = None

PRODUCTS = [
    {
        "external_id": "princess-polly-lavine-mini-dress-white",
        "sku": "lavine-mini-dress-white",
        "name": "Lavine Mini Dress White",
        "price": None,
        "regular_price": None,
        "affiliate_url": "https://click.linksynergy.com/link?id=DXLu4RjC/pk&offerid=1557116.4464839909851562068&type=15&murl=https%3A%2F%2Fus.princesspolly.com%2Fproducts%2Flavine-mini-dress-white",
        "merchant_url": "https://us.princesspolly.com/products/lavine-mini-dress-white",
        "image_url": "https://cdn.shopify.com/s/files/1/0061/8627/0804/products/0-modelinfo-josie-us2_5dc0b987-5db4-4738-bc26-f18aa5c9349d_large.jpg?v=1679009286",
        "category": "dress",
        "style": "LA white mini dress",
        "vibe": "bright going-out",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the LA mini-dress look",
        "city_connection_note": "Selected because it fits the bright, feminine going-out energy of Los Angeles style.",
    },
    {
        "external_id": "princess-polly-gigi-skort-black-petite",
        "sku": "gigi-skort-black-petite",
        "name": "Gigi Skort Black Petite",
        "price": None,
        "regular_price": None,
        "affiliate_url": "https://click.linksynergy.com/link?id=DXLu4RjC/pk&offerid=1557116.4464840197684297812&type=15&murl=https%3A%2F%2Fus.princesspolly.com%2Fproducts%2Fgigi-skort-black-petite",
        "merchant_url": "https://us.princesspolly.com/products/gigi-skort-black-petite",
        "image_url": "https://cdn.shopify.com/s/files/1/0061/8627/0804/files/1-modelinfo-bianca-us4_20f59c0b-0348-476f-9b3b-50e0a9d2d8a8_large.jpg?v=1774909893",
        "category": "skirt",
        "style": "LA black skort",
        "vibe": "clean flirty",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the LA skort look",
        "city_connection_note": "Selected because it brings a clean, flirty mini silhouette that works for casual Los Angeles styling.",
    },
    {
        "external_id": "princess-polly-serenitia-mid-rise-relaxed-jeans-light-wash-petite",
        "sku": "serenitia-mid-rise-relaxed-jeans-light-wash-petite",
        "name": "Serenitia Mid Rise Relaxed Jeans Light Wash Petite",
        "price": None,
        "regular_price": None,
        "affiliate_url": "https://click.linksynergy.com/link?id=DXLu4RjC/pk&offerid=1557116.4464840994697510996&type=15&murl=https%3A%2F%2Fus.princesspolly.com%2Fproducts%2Fserenitia-mid-rise-relaxed-jeans-light-wash-petite",
        "merchant_url": "https://us.princesspolly.com/products/serenitia-mid-rise-relaxed-jeans-light-wash-petite",
        "image_url": "https://cdn.shopify.com/s/files/1/0061/8627/0804/files/0-modelinfo-beanie-us2_cc9b0b56-3d4c-4396-85d6-c9306715275f_large.jpg?v=1766469527",
        "category": "bottoms",
        "style": "LA relaxed denim",
        "vibe": "casual cool",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the LA denim look",
        "city_connection_note": "Selected because relaxed light-wash denim fits the easy, casual-cool side of Los Angeles style.",
    },
    {
        "external_id": "princess-polly-stefenie-denim-skort-mid-wash",
        "sku": "stefenie-denim-skort-mid-wash",
        "name": "Stefenie Denim Skort Mid Wash",
        "price": None,
        "regular_price": None,
        "affiliate_url": "https://click.linksynergy.com/link?id=DXLu4RjC/pk&offerid=1557116.4464841406357504084&type=15&murl=https%3A%2F%2Fus.princesspolly.com%2Fproducts%2Fstefenie-denim-skort-mid-wash",
        "merchant_url": "https://us.princesspolly.com/products/stefenie-denim-skort-mid-wash",
        "image_url": "https://cdn.shopify.com/s/files/1/0061/8627/0804/files/0-modelinfo-summer-us2_8a71a565-cf86-4564-8ce9-e593b6b5913d_large.jpg?v=1774576383",
        "category": "skirt",
        "style": "LA denim skort",
        "vibe": "sunny casual",
        "is_best_seller": False,
        "availability": "in_stock",
        "is_active": True,
        "city_connection_type": "city_inspired_pick",
        "city_connection_location": "Chosen for the LA denim-skirt look",
        "city_connection_note": "Selected because it captures the sunny, casual denim mood that fits Los Angeles style discovery.",
    },
]

SEED = ManualProductSeed(
    key='princess_polly_la',
    source=SOURCE,
    source_file=SOURCE_FILE,
    advertiser_id=ADVERTISER_ID,
    brand_name=BRAND_NAME,
    brand_logo_url=BRAND_LOGO_URL,
    country_code='US',
    country_name='United States',
    city_slug='los-angeles',
    city_name='Los Angeles',
    latitude=Decimal('34.052235'),
    longitude=Decimal('-118.243683'),
    marker_color='#F4A261',
    review_notes='Manually curated Rakuten/Princess Polly Los Angeles products.',
    products=PRODUCTS,
)

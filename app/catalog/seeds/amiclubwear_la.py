from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'cj'
SOURCE_FILE = 'manual-cj-amiclubwear-la'
ADVERTISER_ID = '11168474'
BRAND_NAME = 'AMiClubWear'
BRAND_LOGO_URL = 'https://amiclubwear.com/cdn/shop/files/amiclubwear_logo.jpg?v=1730305339'

PRODUCTS = [{'external_id': 'wh2cla-btp2978x-r-id-wh2000543',
  'sku': 'wh2000543',
  'name': 'Plus Size Ribbed Long Cardigan & Leggings Set',
  'price': Decimal('62.50'),
  'regular_price': Decimal('125.00'),
  'affiliate_url': 'https://www.anrdoezrs.net/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fwh2cla-btp2978x-r-id-wh2000543',
  'merchant_url': 'https://amiclubwear.com/products/wh2cla-btp2978x-r-id-wh2000543',
  'image_url': 'https://amiclubwear.com/cdn/shop/files/WH2000543_1800x1800.jpg?v=1737752309',
  'category': 'bottoms',
  'style': 'LA curve casual',
  'vibe': 'soft-glam lounge',
  'is_best_seller': False},
 {'external_id': 'wh2cla-bd5504-id-wh200249558',
  'sku': 'wh200249558',
  'name': 'Ribbed Halter Neck Backless Bodycon Dress',
  'price': Decimal('24.75'),
  'regular_price': Decimal('42.00'),
  'affiliate_url': 'https://www.tkqlhce.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fwh2cla-bd5504-id-wh200249558',
  'merchant_url': 'https://amiclubwear.com/products/wh2cla-bd5504-id-wh200249558',
  'image_url': 'https://amiclubwear.com/cdn/shop/files/WH200249558_1800x1800.jpg?v=1759467514',
  'category': 'dress',
  'style': 'LA bodycon',
  'vibe': 'night-out',
  'is_best_seller': True},
 {'external_id': 'iri2-6-iset131sets-id-59401b',
  'sku': '59401b',
  'name': 'Crop Tank Top & Cardigan Sweater Set',
  'price': Decimal('23.00'),
  'regular_price': Decimal('46.00'),
  'affiliate_url': 'https://www.jdoqocy.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Firi2-6-iset131sets-id-59401b',
  'merchant_url': 'https://amiclubwear.com/products/iri2-6-iset131sets-id-59401b',
  'image_url': 'https://amiclubwear.com/cdn/shop/files/CC59401B_1800x1800.jpg?v=1744835214',
  'category': 'tops',
  'style': 'LA casual layered',
  'vibe': 'soft city casual',
  'is_best_seller': True},
 {'external_id': 'mable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2',
  'sku': '100100103502572',
  'name': 'MABLE 3 Pieces Sweater Set with Crop Cami, Mini Skirt, Cardigan',
  'price': Decimal('94.99'),
  'regular_price': Decimal('189.99'),
  'affiliate_url': 'https://www.jdoqocy.com/click-101726370-11168474?url=https%3A%2F%2Famiclubwear.com%2Fproducts%2Fmable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2',
  'merchant_url': 'https://amiclubwear.com/products/mable-3-pieces-sweater-set-with-crop-cami-mini-skirt-cardigan-2',
  'image_url': 'https://amiclubwear.com/cdn/shop/files/3bc4bc71-1e36-4761-9d17-a8509c41552b-Max_1800x1800.jpg?v=1726603821',
  'category': 'skirt',
  'style': 'LA boutique set',
  'vibe': 'polished soft glam',
  'is_best_seller': True}]

SEED = ManualProductSeed(
    key='amiclubwear_la',
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
    review_notes='Manually curated CJ/AMIClubWear Los Angeles products.',
    products=PRODUCTS,
)

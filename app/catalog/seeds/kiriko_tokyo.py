from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_seed_types import ManualProductSeed


SOURCE = 'manual'
SOURCE_FILE = 'manual-kiriko-tokyo'
ADVERTISER_ID = 'kiriko-made'
BRAND_NAME = 'Kiriko Made'
BRAND_LOGO_URL = None

PRODUCTS = [{'external_id': 'kiriko-original-v-neck-tunic-sunflower-chijimi',
  'sku': 'KTOK01',
  'name': 'Kiriko x ToK, V-Neck Tunic, Sunflower Chijimi',
  'price': Decimal('98.00'),
  'regular_price': Decimal('98.00'),
  'affiliate_url': 'https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi',
  'merchant_url': 'https://kirikomade.com/products/kiriko-original-v-neck-tunic-sunflower-chijimi',
  'image_url': 'https://kirikomade.com/cdn/shop/files/DYL_8718_720x.png?v=1748454979',
  'category': 'tops',
  'style': 'Tokyo heritage casual',
  'vibe': 'quiet artisan',
  'is_best_seller': False,
  'availability': 'out_of_stock',
  'is_active': True}]

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

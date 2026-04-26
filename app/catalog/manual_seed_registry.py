from __future__ import annotations

from decimal import Decimal

from app.catalog.manual_product_service import ManualProductSeed
from app.scripts import add_manual_amiclubwear_la
from app.scripts import add_manual_kiriko_tokyo
from app.scripts import add_manual_mure_and_grand_nyc
from app.scripts import add_manual_rainbow_nyc


SEEDS: dict[str, ManualProductSeed] = {
    "mure_and_grand_nyc": ManualProductSeed(
        key="mure_and_grand_nyc",
        source=add_manual_mure_and_grand_nyc.SOURCE,
        source_file=add_manual_mure_and_grand_nyc.SOURCE_FILE,
        advertiser_id=add_manual_mure_and_grand_nyc.ADVERTISER_ID,
        brand_name=add_manual_mure_and_grand_nyc.BRAND_NAME,
        brand_logo_url=add_manual_mure_and_grand_nyc.BRAND_LOGO_URL,
        country_code="US",
        country_name="United States",
        city_slug="new-york",
        city_name="New York",
        latitude=Decimal("40.712776"),
        longitude=Decimal("-74.005974"),
        marker_color="#D97706",
        review_notes="Manually curated Mure + Grand NYC products.",
        products=add_manual_mure_and_grand_nyc.PRODUCTS,
    ),
    "rainbow_nyc": ManualProductSeed(
        key="rainbow_nyc",
        source=add_manual_rainbow_nyc.SOURCE,
        source_file=add_manual_rainbow_nyc.SOURCE_FILE,
        advertiser_id=add_manual_rainbow_nyc.ADVERTISER_ID,
        brand_name=add_manual_rainbow_nyc.BRAND_NAME,
        brand_logo_url=add_manual_rainbow_nyc.BRAND_LOGO_URL,
        country_code="US",
        country_name="United States",
        city_slug="new-york",
        city_name="New York",
        latitude=Decimal("40.7128"),
        longitude=Decimal("-74.0060"),
        marker_color="#1D3557",
        review_notes="Manually curated CJ/Rainbow Shops NYC products.",
        products=add_manual_rainbow_nyc.PRODUCTS,
    ),
    "amiclubwear_la": ManualProductSeed(
        key="amiclubwear_la",
        source=add_manual_amiclubwear_la.SOURCE,
        source_file=add_manual_amiclubwear_la.SOURCE_FILE,
        advertiser_id=add_manual_amiclubwear_la.ADVERTISER_ID,
        brand_name=add_manual_amiclubwear_la.BRAND_NAME,
        brand_logo_url=add_manual_amiclubwear_la.BRAND_LOGO_URL,
        country_code="US",
        country_name="United States",
        city_slug="los-angeles",
        city_name="Los Angeles",
        latitude=Decimal("34.052235"),
        longitude=Decimal("-118.243683"),
        marker_color="#F4A261",
        review_notes="Manually curated CJ/AMIClubWear Los Angeles product.",
        products=add_manual_amiclubwear_la.PRODUCTS,
    ),
    "kiriko_tokyo": ManualProductSeed(
        key="kiriko_tokyo",
        source=add_manual_kiriko_tokyo.SOURCE,
        source_file=add_manual_kiriko_tokyo.SOURCE_FILE,
        advertiser_id=add_manual_kiriko_tokyo.ADVERTISER_ID,
        brand_name=add_manual_kiriko_tokyo.BRAND_NAME,
        brand_logo_url=add_manual_kiriko_tokyo.BRAND_LOGO_URL,
        country_code="JP",
        country_name="Japan",
        city_slug="tokyo",
        city_name="Tokyo",
        latitude=Decimal("35.676400"),
        longitude=Decimal("139.650000"),
        marker_color="#E76F51",
        review_notes="Manually curated Kiriko Made Tokyo product.",
        products=add_manual_kiriko_tokyo.PRODUCTS,
    ),
}


def get_manual_seed(key: str) -> ManualProductSeed:
    try:
        return SEEDS[key]
    except KeyError as exc:
        available = ", ".join(sorted(SEEDS))
        raise KeyError(f"Unknown manual seed '{key}'. Available seeds: {available}") from exc

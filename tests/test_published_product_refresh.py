import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.catalog.published_product_refresh import (
    ProductRefreshService,
    RefreshStatus,
    normalize_product_url,
    urls_match_product_identity,
)
from app.database import Base
from app.models import Brand, City, Country, Product, ProductPriceSnapshot


PRODUCT_URL = "https://shop.example.com/products/cream-floral-top"
TRACKED_PRODUCT_URL = (
    f"{PRODUCT_URL}?utm_source=cj&cjevent=abc&cjdata=123"
)


def product_html(
    *,
    title="Cream Floral Printed Shirred Bandeau Top",
    price="40.00",
    regular_price=None,
    currency="USD",
    availability="https://schema.org/InStock",
    url=PRODUCT_URL,
):
    offer = {
        "price": price,
        "availability": availability,
    }
    if currency is not None:
        offer["priceCurrency"] = currency
    if regular_price is not None:
        offer["highPrice"] = regular_price
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "url": url,
        "sku": "cream-floral-top",
        "offers": offer,
    }
    return f"""
    <html>
      <head>
        <title>{title} | Example</title>
        <link rel="canonical" href="{url}">
        <script type="application/ld+json">{json.dumps(payload)}</script>
      </head>
      <body>{title}</body>
    </html>
    """


class FakeResponse:
    def __init__(self, status_code=200, body="", headers=None):
        self.status_code = status_code
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class PublishedProductRefreshTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        country = Country(code="GB", name="United Kingdom")
        city = City(
            slug="london",
            name="London",
            country=country,
            latitude=Decimal("51.5074"),
            longitude=Decimal("-0.1278"),
        )
        brand = Brand(name="Nobody's Child", country=country)
        self.db.add_all([country, city, brand])
        self.db.flush()
        self.product = Product(
            external_id="cream-floral-top",
            source="manual",
            name="Cream Floral Printed Shirred Bandeau Top",
            price=Decimal("40.00"),
            regular_price=None,
            currency="USD",
            affiliate_url=None,
            merchant_url=PRODUCT_URL,
            product_image_url="https://cdn.example.com/top.jpg",
            brand_id=brand.id,
            city_id=city.id,
            is_active=True,
            availability_status="in_stock",
            consecutive_refresh_failures=0,
            needs_refresh_review=False,
        )
        self.db.add(self.product)
        self.db.commit()
        self.checked_at = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def service(self, responses):
        return ProductRefreshService(
            self.db,
            http_client=FakeHttpClient(responses),
            url_validator=lambda value: value.strip().rstrip("|"),
            checked_at=self.checked_at,
        )

    def test_product_page_with_unchanged_price(self):
        result = self.service(
            [FakeResponse(body=product_html())]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.UNCHANGED)
        self.assertEqual(result.detected_price, Decimal("40.00"))
        self.assertFalse(result.would_update)

    def test_product_page_with_lower_current_price(self):
        result = self.service(
            [FakeResponse(body=product_html(price="19.99"))]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.PRICE_CHANGED)
        self.assertEqual(result.detected_price, Decimal("19.99"))
        self.assertEqual(result.confidence, "high")
        self.assertTrue(result.would_update)

    def test_canonical_slug_redirect_keeps_identity_by_product_identifier(self):
        old_url = (
            "https://shop.example.com/products/"
            "wine-faux-leather-skirt-3406068512527"
        )
        canonical_url = (
            "https://shop.example.com/products/"
            "faux-leather-skirt-3406068512527"
        )
        self.product.merchant_url = old_url
        self.product.name = "Faux Leather Mini Pencil Skirt"
        self.db.commit()
        result = self.service(
            [
                FakeResponse(
                    status_code=301,
                    headers={"Location": canonical_url},
                ),
                FakeResponse(
                    body=product_html(
                        title="Faux Leather Mini Pencil Skirt",
                        price="7.48",
                        regular_price="14.97",
                        url=canonical_url,
                    )
                ),
            ]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.PRICE_CHANGED)
        self.assertEqual(result.confidence, "high")
        self.assertTrue(result.would_update)

    def test_product_page_with_sale_and_regular_price(self):
        result = self.service(
            [
                FakeResponse(
                    body=product_html(
                        price="19.99",
                        regular_price="39.99",
                    )
                )
            ]
        ).check_product(self.product)

        self.assertEqual(result.detected_price, Decimal("19.99"))
        self.assertEqual(result.detected_regular_price, Decimal("39.99"))
        self.assertTrue(result.would_update)

    def test_product_url_returning_404(self):
        result = self.service(
            [FakeResponse(status_code=404)]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.PRODUCT_UNAVAILABLE)
        self.assertEqual(result.confidence, "high")

    def test_product_url_returning_410(self):
        result = self.service(
            [FakeResponse(status_code=410)]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.PRODUCT_UNAVAILABLE)
        self.assertIn("410", result.reason)

    def test_product_url_redirecting_to_homepage_with_200(self):
        home_html = """
        <html><head><title>Example | Home</title>
        <link rel="canonical" href="https://shop.example.com/"></head>
        <body>Shop new arrivals</body></html>
        """
        result = self.service(
            [
                FakeResponse(
                    status_code=302,
                    headers={"Location": "/"},
                ),
                FakeResponse(body=home_html),
            ]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.PRODUCT_UNAVAILABLE)
        self.assertEqual(result.final_url, "https://shop.example.com/")
        self.assertIn("Homepage redirect", result.reason)

    def test_product_url_redirecting_to_collection_page(self):
        result = self.service(
            [
                FakeResponse(
                    status_code=302,
                    headers={"Location": "/collections/tops"},
                ),
                FakeResponse(
                    body=(
                        "<html><head><title>Tops</title></head>"
                        "<body>Browse every top</body></html>"
                    )
                ),
            ]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.LIKELY_UNAVAILABLE)
        self.assertTrue(result.would_flag_for_review)

    def test_affiliate_redirects_home_while_original_remains_valid(self):
        self.product.affiliate_url = "https://tracking.example.net/click/123"
        self.db.commit()
        home_html = """
        <html><head><title>Example | Home</title>
        <link rel="canonical" href="https://shop.example.com/"></head>
        <body>Shop new arrivals</body></html>
        """
        result = self.service(
            [
                FakeResponse(body=product_html()),
                FakeResponse(
                    status_code=302,
                    headers={"Location": "https://shop.example.com/"},
                ),
                FakeResponse(body=home_html),
            ]
        ).check_product(self.product)

        self.assertEqual(
            result.refresh_status,
            RefreshStatus.AFFILIATE_LINK_BROKEN,
        )
        self.assertEqual(
            result.affiliate_status,
            RefreshStatus.AFFILIATE_LINK_BROKEN.value,
        )
        self.assertTrue(result.would_flag_for_review)

    def test_merchant_403_or_captcha_is_blocked_unknown(self):
        status_result = self.service(
            [FakeResponse(status_code=403)]
        ).check_product(self.product)
        captcha_result = self.service(
            [
                FakeResponse(
                    body="<html><body>Verify you are human CAPTCHA</body></html>"
                )
            ]
        ).check_product(self.product)

        self.assertEqual(
            status_result.refresh_status,
            RefreshStatus.BLOCKED_OR_UNKNOWN,
        )
        self.assertEqual(
            captcha_result.refresh_status,
            RefreshStatus.BLOCKED_OR_UNKNOWN,
        )

    def test_merchant_429_is_blocked_unknown(self):
        result = self.service(
            [FakeResponse(status_code=429)]
        ).check_product(self.product)

        self.assertEqual(result.refresh_status, RefreshStatus.BLOCKED_OR_UNKNOWN)

    def test_temporary_5xx_or_timeout(self):
        server_result = self.service(
            [FakeResponse(status_code=503)]
        ).check_product(self.product)
        timeout_result = self.service(
            [requests.Timeout()]
        ).check_product(self.product)

        self.assertEqual(
            server_result.refresh_status,
            RefreshStatus.TEMPORARY_FAILURE,
        )
        self.assertEqual(
            timeout_result.refresh_status,
            RefreshStatus.TEMPORARY_FAILURE,
        )

    def test_product_json_ld_extraction(self):
        result = self.service(
            [FakeResponse(body=product_html(price="22.50"))]
        ).check_product(self.product)

        self.assertEqual(result.detected_price, Decimal("22.50"))
        self.assertEqual(result.detected_currency, "USD")
        self.assertEqual(result.confidence, "high")

    def test_currency_is_preserved_when_page_omits_it(self):
        service = self.service(
            [FakeResponse(body=product_html(price="22.50", currency=None))]
        )
        report = service.run([self.product], apply=True)
        self.db.flush()

        self.assertEqual(report.results[0].refresh_status, RefreshStatus.PRICE_CHANGED)
        self.assertEqual(self.product.currency, "USD")
        self.assertEqual(self.product.price, Decimal("22.50"))

    def test_url_comparison_ignores_tracking_parameters_and_trailing_pipe(self):
        self.assertEqual(
            normalize_product_url(f" {TRACKED_PRODUCT_URL}| "),
            normalize_product_url(PRODUCT_URL),
        )
        self.assertTrue(
            urls_match_product_identity(TRACKED_PRODUCT_URL, PRODUCT_URL)
        )

    def test_dry_run_makes_no_database_changes(self):
        service = self.service(
            [FakeResponse(body=product_html(price="19.99"))]
        )
        before = (
            self.product.price,
            self.product.last_refresh_status,
            self.product.last_product_checked_at,
            self.product.consecutive_refresh_failures,
        )
        report = service.run([self.product], apply=False)
        after = (
            self.product.price,
            self.product.last_refresh_status,
            self.product.last_product_checked_at,
            self.product.consecutive_refresh_failures,
        )

        self.assertEqual(report.mode, "dry_run")
        self.assertEqual(before, after)
        self.assertEqual(
            self.db.query(ProductPriceSnapshot).count(),
            0,
        )

    def test_apply_updates_only_confirmed_price(self):
        second = Product(
            external_id="unmatched",
            source="manual",
            name="Completely Different Stored Name",
            price=Decimal("40.00"),
            currency="USD",
            merchant_url="https://shop.example.com/products/unmatched",
            brand_id=self.product.brand_id,
            city_id=self.product.city_id,
            is_active=True,
            availability_status="in_stock",
            consecutive_refresh_failures=0,
            needs_refresh_review=False,
        )
        self.db.add(second)
        self.db.commit()
        low_confidence_html = product_html(
            title="Unrelated Merchant Product",
            price="15.00",
            url="https://shop.example.com/products/something-else",
        )
        service = self.service(
            [
                FakeResponse(body=product_html(price="19.99")),
                FakeResponse(body=low_confidence_html),
            ]
        )
        report = service.run([self.product, second], apply=True)
        self.db.flush()

        self.assertEqual(self.product.price, Decimal("19.99"))
        self.assertEqual(second.price, Decimal("40.00"))
        self.assertTrue(report.results[0].would_update)
        self.assertFalse(report.results[1].would_update)
        self.assertEqual(
            self.db.query(ProductPriceSnapshot).count(),
            1,
        )

    def test_apply_flags_suspicious_without_deleting_or_unpublishing(self):
        service = self.service([FakeResponse(status_code=404)])
        report = service.run([self.product], apply=True)
        self.db.flush()

        self.assertEqual(
            report.results[0].refresh_status,
            RefreshStatus.PRODUCT_UNAVAILABLE,
        )
        self.assertTrue(self.product.needs_refresh_review)
        self.assertTrue(self.product.is_active)
        self.assertIsNone(self.product.deactivated_at)
        self.assertEqual(self.db.query(Product).count(), 1)

    def test_consecutive_failure_count_increments_and_resets(self):
        service = self.service(
            [
                FakeResponse(status_code=404),
                FakeResponse(body=product_html()),
            ]
        )
        failed = service.check_product(self.product)
        service.apply_result(self.product, failed)
        self.assertEqual(self.product.consecutive_refresh_failures, 1)

        recovered = service.check_product(self.product)
        service.apply_result(self.product, recovered)

        self.assertEqual(recovered.refresh_status, RefreshStatus.UNCHANGED)
        self.assertEqual(self.product.consecutive_refresh_failures, 0)
        self.assertFalse(self.product.needs_refresh_review)
        self.assertTrue(self.product.is_active)


if __name__ == "__main__":
    unittest.main()

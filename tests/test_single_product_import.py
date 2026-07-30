import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.city_assignment import CityScanMode
from app.curation.single_product import (
    NotProductPageError,
    ProductUrlValidationError,
    SingleProductPage,
    fetch_single_product_page,
    import_single_product_candidate,
)
from app.database import Base
from app.models import ProductCandidate
from app.routers.catalog_admin import SingleProductImportRequest


PRODUCT_HTML = b"""
<html>
  <head>
    <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "Architectural Pleated Midi Dress",
        "url": "https://shop.example.com/products/pleated-midi-dress",
        "brand": {"name": "Example Atelier"},
        "description": "A sculptural pleated cotton midi dress.",
        "image": ["https://cdn.example.com/pleated-midi-dress.jpg"],
        "offers": {
          "price": "189.00",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      }
    </script>
  </head>
</html>
"""


def _public_dns(*_args, **_kwargs):
    return [
        (
            2,
            1,
            6,
            "",
            ("93.184.216.34", 443),
        )
    ]


class SingleProductRequestTests(unittest.TestCase):
    def test_accepts_the_explicit_camel_case_auto_contract(self):
        request = SingleProductImportRequest.model_validate(
            {
                "url": "https://shop.example.com/products/dress",
                "sourceType": "single_product",
                "cityMode": "auto",
                "cityId": None,
                "categoryId": "dresses",
            }
        )

        self.assertEqual(request.source_type, "single_product")
        self.assertEqual(request.city_mode, CityScanMode.AUTO)
        self.assertIsNone(request.city_id)
        self.assertEqual(request.category_id, "dress")

    def test_selected_mode_requires_a_city_override(self):
        with self.assertRaises(ValidationError) as raised:
            SingleProductImportRequest.model_validate(
                {
                    "url": "https://shop.example.com/products/dress",
                    "sourceType": "single_product",
                    "cityMode": "selected",
                }
            )

        self.assertIn("cityId is required", str(raised.exception))

    def test_auto_mode_does_not_silently_accept_a_city_override(self):
        with self.assertRaises(ValidationError) as raised:
            SingleProductImportRequest.model_validate(
                {
                    "url": "https://shop.example.com/products/dress",
                    "sourceType": "single_product",
                    "cityMode": "auto",
                    "cityId": "london",
                }
            )

        self.assertIn("cityId must be omitted", str(raised.exception))


class SingleProductPageDetectionTests(unittest.TestCase):
    @patch(
        "app.curation.single_product.socket.getaddrinfo",
        side_effect=_public_dns,
    )
    @patch("app.curation.single_product.requests.get")
    def test_extracts_a_matching_json_ld_product(self, mock_get, _mock_dns):
        mock_get.return_value = Mock(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=PRODUCT_HTML,
        )

        result = fetch_single_product_page(
            "https://shop.example.com/products/pleated-midi-dress"
        )

        self.assertEqual(
            result.discovery_method,
            "single_product_structured_data",
        )
        self.assertEqual(
            result.product["title"],
            "Architectural Pleated Midi Dress",
        )
        self.assertEqual(result.product["_currency"], "USD")

    @patch(
        "app.curation.single_product.socket.getaddrinfo",
        side_effect=_public_dns,
    )
    @patch("app.curation.single_product.requests.get")
    def test_rejects_a_collection_page_with_product_cards(self, mock_get, _mock_dns):
        html = b"""
        <script type="application/ld+json">
          [
            {
              "@type": "Product",
              "name": "First Dress",
              "url": "/products/first-dress",
              "image": "/images/first.jpg",
              "offers": {"price": "99.00", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "name": "Second Dress",
              "url": "/products/second-dress",
              "image": "/images/second.jpg",
              "offers": {"price": "109.00", "priceCurrency": "USD"}
            }
          ]
        </script>
        """
        mock_get.return_value = Mock(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=html,
        )

        with self.assertRaises(NotProductPageError):
            fetch_single_product_page(
                "https://shop.example.com/collections/dresses"
            )

    @patch("app.curation.single_product.requests.get")
    def test_blocks_private_network_urls_before_fetching(self, mock_get):
        with self.assertRaises(ProductUrlValidationError):
            fetch_single_product_page("http://127.0.0.1/products/private")

        mock_get.assert_not_called()


class SingleProductCandidateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @patch("app.curation.single_product.fetch_single_product_page")
    def test_creates_one_pending_candidate_with_three_city_recommendations(
        self,
        mock_fetch,
    ):
        product_url = "https://shop.example.com/products/pleated-midi-dress"
        mock_fetch.return_value = SingleProductPage(
            canonical_url=product_url,
            product={
                "id": "retailer-id",
                "title": "Architectural Pleated Midi Dress",
                "handle": "pleated-midi-dress",
                "vendor": "Example Atelier",
                "product_type": "Dress",
                "body_html": "A sculptural pleated cotton midi dress.",
                "tags": ["pleated", "cotton", "architectural"],
                "variants": [{"price": "189.00", "available": True}],
                "images": [
                    {
                        "src": (
                            "https://cdn.example.com/"
                            "pleated-midi-dress.jpg"
                        )
                    }
                ],
                "_currency": "USD",
                "_merchant_url": product_url,
            },
            discovery_method="single_product_structured_data",
            attempts=(
                {
                    "method": "single_product_page",
                    "status": "succeeded",
                    "detail": "The public retailer page was fetched.",
                },
            ),
        )

        result = import_single_product_candidate(
            self.db,
            url=product_url,
            city_mode="auto",
            target_city_slug=None,
            category_override="tops",
            active_city_slugs=("london", "new-york", "copenhagen"),
            scan_run_id="scan_single_test",
        )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["found"], 1)
        self.assertEqual(len(result["recommendations"]), 3)
        self.assertTrue(
            all(item["explanation"] for item in result["recommendations"])
        )
        self.assertEqual(result["candidate"]["source_type"], "single_product")
        self.assertEqual(result["candidate"]["normalized_category"], "tops")
        self.assertEqual(
            result["candidate"]["scoring_mode"],
            "strict_distinctiveness",
        )
        self.assertEqual(result["candidate"]["review_status"], "pending")

        row = self.db.query(ProductCandidate).one()
        self.assertEqual(row.source, "single_product")
        self.assertEqual(row.scan_run_id, "scan_single_test")
        self.assertEqual(len(row.city_candidates), 3)


if __name__ == "__main__":
    unittest.main()

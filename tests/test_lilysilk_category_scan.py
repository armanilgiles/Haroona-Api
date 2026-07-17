import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from app.curation.lilysilk_category import (
    LILYSILK_IMAGE_PREFIX,
    LilySilkFetchResult,
    _fetch_lilysilk_category_result,
    build_lilysilk_candidate_payload_result,
)
from app.curation.scanner_registry import detect_curation_scanner
from app.curation.scoring import HYBRID_SCORING_VERSION
from app.curation.shopify_collection import CollectionScanOptions
from app.curation.shopify_image_selection import ShopifyImageSelection


SOURCE_URL = (
    "https://www.lilysilk.com/us/category/womentops.html"
    "?cs=navbar01-1menu04&cn=20250218"
)


def _lilysilk_product() -> dict:
    return {
        "id": 12345,
        "spu": "2116",
        "title": "The Amalfi Stripe Silk Shirt",
        "url": "the-amalfi-stripe-silk-shirt",
        "description": "A relaxed silk shirt for polished city dressing.",
        "status": 2,
        "discountMinPrice": {
            "cent": 7900,
            "precision": 2,
            "currency": "USD",
        },
        "spuImg": [
            {
                "url": (
                    "/2/1/2116-blue-stripe-1.jpg?width=600&quality=90"
                    "?width=600&quality=90"
                ),
                "isMain": True,
                "index": 1,
            }
        ],
        "gaAttribute": {"pcat": "Women Tops"},
        "categoryGa": {"category": ["Women", "Tops", "Silk Shirts"]},
        "defaultColor": "Blue Stripe",
    }


class LilySilkCategoryScanTests(unittest.TestCase):
    def setUp(self):
        self.options = CollectionScanOptions(
            source_url=SOURCE_URL,
            merchant_name="LILYSILK",
            target_city_slug="london",
            source="lilysilk",
            source_type="category",
            limit=1,
            image_mode="smart",
        )

    def test_registry_recognizes_lilysilk_category_with_query_parameters(self):
        scanner = detect_curation_scanner(SOURCE_URL)

        self.assertEqual(scanner.name, "lilysilk_category")
        self.assertEqual(scanner.source, "lilysilk")
        self.assertEqual(scanner.source_type, "category")
        self.assertEqual(scanner.supported_image_modes, ("fast", "smart"))
        self.assertEqual(scanner.default_image_mode, "smart")

    @patch("app.curation.lilysilk_category.requests.post")
    @patch("app.curation.lilysilk_category.requests.get")
    def test_fetches_products_from_lilysilk_category_api(self, mock_get, mock_post):
        page_response = Mock(status_code=200)
        page_response.text = (
            r'<script>self.__next_f.push([1,"categoryId":938342394081137,'
            r'"lilysilkCategoryId":14])</script>'
        )
        mock_get.return_value = page_response

        api_response = Mock(status_code=200)
        api_response.json.return_value = {
            "success": True,
            "data": {"productList": [_lilysilk_product(), _lilysilk_product()]},
            "page": {"total": 2},
        }
        mock_post.return_value = api_response

        result = _fetch_lilysilk_category_result(self.options)

        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.pages_scanned, 1)
        self.assertFalse(result.source_truncated)
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://www.lilysilk.com/us/category/womentops.html",
        )
        self.assertEqual(mock_post.call_args.kwargs["json"]["categoryId"], 938342394081137)
        self.assertEqual(mock_post.call_args.kwargs["json"]["pageSize"], 250)

    @patch("app.curation.lilysilk_category.select_shopify_product_image")
    @patch("app.curation.lilysilk_category._fetch_lilysilk_category_result")
    def test_builds_candidate_with_canonical_urls_and_price(
        self,
        mock_fetch,
        mock_select_image,
    ):
        mock_fetch.return_value = LilySilkFetchResult(
            products=[_lilysilk_product()],
            pages_scanned=1,
            source_truncated=False,
        )
        selected_image = f"{LILYSILK_IMAGE_PREFIX}/2/1/2116-blue-stripe-1.jpg"
        mock_select_image.return_value = ShopifyImageSelection(
            url=selected_image,
            score=82,
            candidates_checked=1,
        )

        result = build_lilysilk_candidate_payload_result(self.options)

        self.assertEqual(len(result.payloads), 1)
        candidate = result.payloads[0]
        self.assertEqual(candidate.source, "lilysilk")
        self.assertEqual(candidate.source_type, "category")
        self.assertEqual(
            candidate.source_url,
            "https://www.lilysilk.com/us/category/womentops.html",
        )
        self.assertEqual(
            candidate.merchant_url,
            "https://www.lilysilk.com/us/product/the-amalfi-stripe-silk-shirt.html",
        )
        self.assertEqual(candidate.price_amount, Decimal("79.00"))
        self.assertEqual(candidate.currency, "USD")
        self.assertEqual(candidate.normalized_category, "tops")
        self.assertEqual(candidate.image_url, selected_image)
        self.assertIsNotNone(candidate.platform_alignment_score)
        self.assertEqual(candidate.scoring_version, HYBRID_SCORING_VERSION)
        self.assertEqual(len(candidate.city_fit_scores), 12)
        self.assertEqual(
            mock_select_image.call_args.args[0][0].url,
            selected_image,
        )


if __name__ == "__main__":
    unittest.main()

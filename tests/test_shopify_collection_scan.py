import unittest
from unittest.mock import Mock, patch

import requests

from app.curation.shopify_collection import (
    CollectionRateLimitedError,
    CollectionScanOptions,
    ShopifyFetchResult,
    _HOST_RATE_LIMIT_UNTIL,
    _fetch_shopify_collection_result,
    build_candidate_payload_result,
)
from app.curation.shopify_image_selection import ShopifyImageSelection
from app.curation.storefront_discovery import (
    DiscoveryAttempt,
    StorefrontDiscoveryResult,
)


def _shopify_product(product_id: int, *, valid: bool = True) -> dict:
    return {
        "id": product_id,
        "title": "City Dress" if valid else "",
        "handle": f"city-dress-{product_id}",
        "vendor": "Example",
        "product_type": "Dress",
        "variants": [{"price": "79.00", "available": True}],
        "images": [{"src": f"https://cdn.example.com/{product_id}.jpg"}],
    }


def _sold_out_shopify_product(product_id: int) -> dict:
    product = _shopify_product(product_id)
    product["title"] = "Playful Printed Smock Mini Dress"
    product["tags"] = ["volume", "skirt", "cute", "statement"]
    product["variants"] = [{"price": "89.00", "available": False}]
    return product


def _editorial_brand_product(product_id: int) -> dict:
    product = _shopify_product(product_id)
    product["title"] = "Diane von Furstenberg Silk Wrap Dress"
    product["vendor"] = "Diane von Furstenberg"
    product["body_html"] = "A structured silk wrap dress."
    return product


def _low_platform_high_city_product(product_id: int) -> dict:
    product = _shopify_product(product_id)
    product["title"] = "FASHNZFAB Asymmetrical Technical Layered Utility Dress"
    product["vendor"] = "FASHNZFAB"
    return product


class ShopifyCollectionScanTests(unittest.TestCase):
    def setUp(self):
        _HOST_RATE_LIMIT_UNTIL.clear()
        self.options = CollectionScanOptions(
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            limit=2,
            image_mode="smart",
        )

    def tearDown(self):
        _HOST_RATE_LIMIT_UNTIL.clear()

    @patch("app.curation.shopify_collection.requests.get")
    def test_fetches_a_second_source_page_when_the_first_page_is_full(self, mock_get):
        first_response = Mock(status_code=200)
        first_response.json.return_value = {
            "products": [_shopify_product(index) for index in range(250)]
        }
        second_response = Mock(status_code=200)
        second_response.json.return_value = {
            "products": [_shopify_product(index) for index in range(250, 260)]
        }
        mock_get.side_effect = [first_response, second_response]

        result = _fetch_shopify_collection_result(self.options)

        self.assertEqual(len(result.products), 260)
        self.assertEqual(result.pages_scanned, 2)
        self.assertFalse(result.source_truncated)
        self.assertEqual(result.discovery_method, "shopify_collection_json")
        self.assertFalse(result.fallback_used)
        self.assertIn("page=2", mock_get.call_args_list[1].args[0])

    @patch("app.curation.shopify_collection.time.sleep")
    @patch("app.curation.shopify_collection.requests.get")
    def test_retries_a_transient_shopify_timeout(self, mock_get, mock_sleep):
        success_response = Mock(status_code=200)
        success_response.json.return_value = {"products": [_shopify_product(1)]}
        mock_get.side_effect = [requests.Timeout("slow response"), success_response]

        result = _fetch_shopify_collection_result(self.options)

        self.assertEqual(len(result.products), 1)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(result.discovery_attempts[0]["status"], "retried")
        self.assertEqual(result.discovery_attempts[-1]["status"], "succeeded")

    @patch("app.curation.shopify_collection.requests.get")
    def test_uses_a_smaller_json_page_when_the_large_page_fails(self, mock_get):
        unavailable_response = Mock(status_code=404)
        success_response = Mock(status_code=200)
        success_response.json.return_value = {"products": [_shopify_product(1)]}
        mock_get.side_effect = [unavailable_response, success_response]

        result = _fetch_shopify_collection_result(self.options)

        self.assertEqual(len(result.products), 1)
        self.assertIn("limit=250", mock_get.call_args_list[0].args[0])
        self.assertIn("limit=100", mock_get.call_args_list[1].args[0])
        self.assertIn("page size of 100", result.discovery_attempts[-1]["detail"])

    @patch("app.curation.shopify_collection.discover_storefront_products")
    @patch("app.curation.shopify_collection.requests.get")
    def test_rate_limit_stops_requests_and_starts_host_cooldown(
        self,
        mock_get,
        mock_discover,
    ):
        mock_get.return_value = Mock(
            status_code=429,
            headers={"Retry-After": "120"},
        )

        with self.assertRaises(CollectionRateLimitedError) as context:
            _fetch_shopify_collection_result(self.options)

        self.assertEqual(mock_get.call_count, 1)
        mock_discover.assert_not_called()
        self.assertEqual(context.exception.retry_after_seconds, 120)
        self.assertEqual(context.exception.attempts[-1]["status"], "rate_limited")

        with self.assertRaises(CollectionRateLimitedError):
            _fetch_shopify_collection_result(self.options)
        self.assertEqual(mock_get.call_count, 1)

    @patch("app.curation.shopify_collection.discover_storefront_products")
    @patch("app.curation.shopify_collection.requests.get")
    def test_uses_storefront_fallback_when_shopify_json_is_unavailable(
        self,
        mock_get,
        mock_discover,
    ):
        mock_get.return_value = Mock(status_code=404)
        mock_discover.return_value = StorefrontDiscoveryResult(
            products=[_shopify_product(1)],
            discovery_method="product_page_crawl",
            pages_scanned=2,
            source_truncated=False,
            attempts=(
                DiscoveryAttempt(
                    method="public_storefront_html",
                    status="succeeded",
                    detail="The public collection page was fetched.",
                ),
                DiscoveryAttempt(
                    method="product_page_crawl",
                    status="succeeded",
                    detail="Parsed one product page.",
                ),
            ),
        )

        result = _fetch_shopify_collection_result(self.options)

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.discovery_method, "product_page_crawl")
        self.assertEqual(result.pages_scanned, 2)
        self.assertIn("used public product pages", result.warnings[0])
        self.assertEqual(result.discovery_attempts[-1]["status"], "succeeded")

    @patch("app.curation.shopify_collection.discover_storefront_products")
    @patch("app.curation.shopify_collection.requests.get")
    def test_storefront_fallback_preserves_category_query_parameters(
        self,
        mock_get,
        mock_discover,
    ):
        mock_get.return_value = Mock(status_code=404)
        mock_discover.return_value = StorefrontDiscoveryResult(
            products=[_shopify_product(1)],
            discovery_method="embedded_storefront_data",
            pages_scanned=1,
            source_truncated=False,
            attempts=(),
        )
        source_url = (
            "https://global.example.com/us/category/100?"
            "category1DepthCode=100&gender=F#products"
        )
        options = CollectionScanOptions(
            source_url=source_url,
            merchant_name="Example",
            limit=2,
        )

        _fetch_shopify_collection_result(options)

        self.assertEqual(
            mock_discover.call_args.args[0],
            "https://global.example.com/us/category/100?"
            "category1DepthCode=100&gender=F",
        )

    @patch("app.curation.shopify_collection.select_shopify_product_image")
    @patch("app.curation.shopify_collection._fetch_shopify_collection_result")
    def test_limit_is_filled_after_invalid_images_are_skipped(
        self,
        mock_fetch,
        mock_select_image,
    ):
        mock_fetch.return_value = ShopifyFetchResult(
            products=[
                _shopify_product(1, valid=False),
                _shopify_product(2),
                _shopify_product(3),
                _shopify_product(4),
                _shopify_product(5),
            ],
            pages_scanned=1,
            source_truncated=False,
        )
        mock_select_image.side_effect = [
            ShopifyImageSelection(url=None, score=12, candidates_checked=3),
            ShopifyImageSelection(
                url="https://cdn.example.com/3.jpg",
                score=80,
                candidates_checked=2,
            ),
            ShopifyImageSelection(
                url="https://cdn.example.com/4.jpg",
                score=70,
                candidates_checked=2,
            ),
        ]

        result = build_candidate_payload_result(self.options)

        self.assertEqual(result.discovered_count, 5)
        self.assertEqual(len(result.payloads), 2)
        self.assertEqual(result.skipped_invalid_products, 1)
        self.assertEqual(result.skipped_missing_images, 1)
        self.assertEqual(result.skipped_due_to_limit, 1)
        self.assertEqual(result.image_candidates_checked, 7)

    @patch("app.curation.shopify_collection.select_shopify_product_image")
    @patch("app.curation.shopify_collection._fetch_shopify_collection_result")
    def test_sold_out_products_are_removed_before_ranking_and_image_checks(
        self,
        mock_fetch,
        mock_select_image,
    ):
        mock_fetch.return_value = ShopifyFetchResult(
            products=[
                _sold_out_shopify_product(1),
                _shopify_product(2),
                _shopify_product(3),
            ],
            pages_scanned=1,
            source_truncated=False,
        )
        mock_select_image.side_effect = [
            ShopifyImageSelection(
                url="https://cdn.example.com/2.jpg",
                score=80,
                candidates_checked=1,
            ),
            ShopifyImageSelection(
                url="https://cdn.example.com/3.jpg",
                score=75,
                candidates_checked=1,
            ),
        ]

        result = build_candidate_payload_result(self.options)

        self.assertEqual([item.external_product_id for item in result.payloads], ["2", "3"])
        self.assertEqual(result.skipped_ineligible_products, 1)
        self.assertEqual(result.ineligible_reason_counts, {"out_of_stock": 1})
        self.assertEqual(mock_select_image.call_count, 2)

    @patch("app.curation.shopify_collection.select_shopify_product_image")
    @patch("app.curation.shopify_collection._fetch_shopify_collection_result")
    def test_platform_ready_candidate_ranks_before_high_city_fit_low_trust_item(
        self,
        mock_fetch,
        mock_select_image,
    ):
        options = CollectionScanOptions(
            source_url=self.options.source_url,
            merchant_name=self.options.merchant_name,
            target_city_slug="tokyo",
            limit=1,
            image_mode="smart",
        )

        mock_fetch.return_value = ShopifyFetchResult(
            products=[
                _low_platform_high_city_product(1),
                _editorial_brand_product(2),
            ],
            pages_scanned=1,
            source_truncated=False,
        )
        mock_select_image.return_value = ShopifyImageSelection(
            url="https://cdn.example.com/2.jpg",
            score=80,
            candidates_checked=1,
        )

        result = build_candidate_payload_result(options)

        self.assertEqual(len(result.payloads), 1)
        self.assertEqual(result.payloads[0].external_product_id, "2")
        self.assertGreaterEqual(result.payloads[0].platform_alignment_score, 7)


if __name__ == "__main__":
    unittest.main()

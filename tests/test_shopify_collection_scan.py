import unittest
from unittest.mock import Mock, patch

from app.curation.shopify_collection import (
    CollectionScanOptions,
    ShopifyFetchResult,
    _fetch_shopify_collection_result,
    build_candidate_payload_result,
)
from app.curation.shopify_image_selection import ShopifyImageSelection


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


class ShopifyCollectionScanTests(unittest.TestCase):
    def setUp(self):
        self.options = CollectionScanOptions(
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            limit=2,
            image_mode="smart",
        )

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
        self.assertIn("page=2", mock_get.call_args_list[1].args[0])

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


if __name__ == "__main__":
    unittest.main()

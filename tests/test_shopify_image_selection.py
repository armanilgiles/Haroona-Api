import unittest
from unittest.mock import patch

from app.curation.shopify_image_selection import (
    ShopifyImageCandidate,
    image_candidates_from_shopify_product,
    select_shopify_product_image,
)


class ShopifyImageSelectionTests(unittest.TestCase):
    def test_shopify_gallery_is_deduplicated_and_keeps_primary_first(self):
        product = {
            "image": {"src": "https://cdn.example.com/primary.jpg"},
            "images": [
                {"src": "https://cdn.example.com/primary.jpg"},
                {
                    "src": "https://cdn.example.com/model.jpg",
                    "alt": "Model wearing dress",
                    "width": 800,
                    "height": 1200,
                },
                {"src": "not-a-url"},
            ],
        }

        candidates = image_candidates_from_shopify_product(product)

        self.assertEqual(
            [candidate.url for candidate in candidates],
            [
                "https://cdn.example.com/primary.jpg",
                "https://cdn.example.com/model.jpg",
            ],
        )

    @patch("app.curation.shopify_image_selection._cached_image_url_loads")
    def test_fast_uses_first_image_that_loads(self, mock_loads):
        mock_loads.side_effect = [False, True]
        candidates = [
            ShopifyImageCandidate(url="https://cdn.example.com/broken.jpg"),
            ShopifyImageCandidate(url="https://cdn.example.com/working.jpg"),
        ]

        selection = select_shopify_product_image(
            candidates,
            image_mode="fast",
            referer="https://shop.example.com/collections/new",
        )

        self.assertEqual(selection.url, "https://cdn.example.com/working.jpg")
        self.assertEqual(selection.candidates_checked, 2)

    @patch("app.curation.shopify_image_selection._score_likely_model_worn_image")
    @patch("app.curation.shopify_image_selection._cached_download_image_preview")
    def test_smart_chooses_the_strongest_verified_gallery_image(
        self,
        mock_preview,
        mock_content_score,
    ):
        mock_preview.side_effect = (
            lambda image_url, **_: b"model" if "model" in image_url else b"flat"
        )
        mock_content_score.side_effect = (
            lambda preview: 80 if preview == b"model" else 5
        )
        candidates = [
            ShopifyImageCandidate(
                url="https://cdn.example.com/flat.jpg",
                width=1000,
                height=1000,
                position=1,
            ),
            ShopifyImageCandidate(
                url="https://cdn.example.com/model.jpg",
                width=1000,
                height=1000,
                position=2,
            ),
        ]

        selection = select_shopify_product_image(
            candidates,
            image_mode="smart",
            referer="https://shop.example.com/collections/new",
        )

        self.assertEqual(selection.url, "https://cdn.example.com/model.jpg")
        self.assertEqual(selection.candidates_checked, 2)

    @patch("app.curation.shopify_image_selection._score_likely_model_worn_image")
    @patch("app.curation.shopify_image_selection._cached_download_image_preview")
    def test_model_only_rejects_a_low_confidence_image(
        self,
        mock_preview,
        mock_content_score,
    ):
        mock_preview.return_value = b"low-confidence"
        mock_content_score.return_value = 5

        selection = select_shopify_product_image(
            [ShopifyImageCandidate(url="https://cdn.example.com/product.jpg")],
            image_mode="model_only",
            referer="https://shop.example.com/collections/new",
        )

        self.assertIsNone(selection.url)
        self.assertEqual(selection.candidates_checked, 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.shopify_collection import (
    CollectionRateLimitedError,
    CollectionScanOptions,
    scan_and_save_shopify_collection,
)
from app.database import Base
from app.models import ProductCandidate


class ShopifyRateLimitRecoveryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.source_url = "https://shop.example.com/collections/dresses"
        self.candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url=self.source_url,
            scan_run_id="scan_old",
            merchant_name="Example Store",
            brand_name="Example Brand",
            merchant_verification="unverified",
            external_product_id="cached-1",
            title="Striped Cotton Polo Shirt Dress",
            description="A preppy cotton polo dress for everyday city wear.",
            price_amount=Decimal("129.00"),
            currency="USD",
            merchant_url="https://shop.example.com/products/cached-1",
            image_url="https://cdn.example.com/cached-1.jpg",
            availability="in_stock",
            normalized_category="dress",
            target_city_slug="new-york",
            eligibility_status="eligible",
            eligibility_reasons=[],
            platform_alignment_score=Decimal("8.0"),
            platform_alignment_reasons=["Recognized brand"],
            city_fit_score=75,
            city_fit_scores={"new-york": 75},
            scoring_method="deterministic_rules",
            scoring_version="old",
            haroona_score=75,
            score_reasons=[],
            review_status="pending",
        )
        self.db.add(self.candidate)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    @patch("app.curation.shopify_collection.build_candidate_payload_result")
    def test_saved_products_are_rescored_when_fresh_source_is_rate_limited(
        self,
        mock_build,
    ):
        mock_build.side_effect = CollectionRateLimitedError(
            "Storefront rate limited the scan.",
            retry_after_seconds=300,
            attempts=[
                {
                    "method": "shopify_collection_json",
                    "status": "rate_limited",
                    "detail": "HTTP 429",
                }
            ],
        )
        options = CollectionScanOptions(
            source_url=self.source_url,
            merchant_name="Example Store",
            target_city_slug="london",
            limit=25,
            scan_run_id="scan_new",
            merchant_verification="unverified",
        )

        result = scan_and_save_shopify_collection(self.db, options)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["found"], 1)
        self.assertEqual(
            result["summary"]["discovery"]["method"],
            "cached_product_candidates",
        )
        self.assertTrue(result["summary"]["discovery"]["fallback_used"])
        self.assertIn("HTTP 429", result["warnings"][0])

        self.db.refresh(self.candidate)
        self.assertEqual(self.candidate.scan_run_id, "scan_new")
        self.assertEqual(self.candidate.target_city_slug, "london")
        self.assertEqual(self.candidate.review_status, "pending")


if __name__ == "__main__":
    unittest.main()

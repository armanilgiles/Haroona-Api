import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.scan_observability import build_scan_observability
from app.curation.scan_runs import (
    complete_scan_run,
    start_scan_run,
    update_scan_run_context,
)
from app.database import Base
from app.models import (
    Brand,
    City,
    Country,
    FashionConceptAlias,
    FashionConceptProposal,
    Product,
    ProductCandidate,
)


class ScanObservabilityTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        country = Country(code="GB", name="United Kingdom")
        city = City(
            slug="london",
            name="London",
            country=country,
            latitude=51.5074,
            longitude=-0.1278,
        )
        brand = Brand(name="Example", country=country)
        self.db.add_all([country, city, brand])
        self.db.flush()

        self.run = start_scan_run(
            self.db,
            scan_run_id="scan_observability",
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            target_city_slug="london",
            normalized_category="dress",
            requested_image_mode="smart",
            requested_limit=25,
        )
        update_scan_run_context(
            self.db,
            self.run,
            merchant_name="Example",
            scanner_name="shopify_collection",
            source="shopify",
            source_type="collection",
            merchant_verification="verified",
            effective_image_mode="smart",
        )

        product = Product(
            external_id="observable-1",
            source="shopify",
            name="Cotton Lace Floracore Quiltoria Dress",
            currency="USD",
            affiliate_url="https://tracking.example.com/observable-1",
            merchant_url="https://shop.example.com/products/observable-1",
            product_image_url="https://cdn.example.com/observable-1.jpg",
            brand_id=brand.id,
            city_id=city.id,
            is_active=True,
            availability_status="in_stock",
        )
        self.db.add(product)
        self.db.flush()

        self.candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url=self.run.source_url,
            scan_run_id=self.run.id,
            merchant_name="Example",
            brand_name="Example",
            merchant_verification="verified",
            external_product_id="observable-1",
            title="Cotton Lace Floracore Quiltoria Dress",
            description="A cotton lace dress with a fitted silhouette.",
            price_amount=79,
            currency="USD",
            merchant_url="https://shop.example.com/products/observable-1",
            affiliate_url="https://tracking.example.com/observable-1",
            affiliate_link_status="verified",
            image_url="https://cdn.example.com/observable-1.jpg",
            availability="in_stock",
            normalized_category="dress",
            target_city_slug="london",
            eligibility_status="eligible",
            eligibility_reasons=[],
            platform_alignment_score=6.2,
            platform_alignment_reasons=["Advisory only"],
            city_fit_score=86,
            city_fit_scores={"london": 86},
            scoring_version="hybrid_v1_1",
            scoring_mode="legacy",
            scoring_analysis={"scored_at": "2026-07-01T12:00:00+00:00"},
            haroona_score=86,
            score_reasons=[],
            review_status="approved",
            promoted_product_id=product.id,
        )
        self.db.add(self.candidate)
        self.db.commit()

        complete_scan_run(
            self.db,
            self.run,
            result={
                "items": [{"external_product_id": self.candidate.external_product_id}],
                "summary": {
                    "discovered": 1,
                    "selected_for_review": 1,
                    "saved": 1,
                    "created": 1,
                    "updated": 0,
                    "skipped_total": 0,
                    "discovery": {
                        "method": "embedded_storefront_data",
                        "fallback_used": True,
                        "attempts": [
                            {
                                "method": "shopify_collection_json",
                                "status": "failed",
                                "detail": "The JSON endpoint returned 404.",
                            },
                            {
                                "method": "embedded_storefront_data",
                                "status": "succeeded",
                                "detail": "Embedded product data was found.",
                            },
                        ],
                    },
                },
            },
            warnings=[],
        )

        reviewed_at = datetime(2026, 7, 2, 12, tzinfo=timezone.utc)
        candidate_key = "shopify:observable-1"
        self.db.add_all(
            [
                FashionConceptAlias(
                    normalized_phrase="floracore",
                    display_phrase="floracore",
                    concept_id="cottagecore_dress",
                    source="proposal_review",
                    active=True,
                    created_by="test-curator",
                    created_at=reviewed_at,
                ),
                FashionConceptProposal(
                    normalized_phrase="floracore",
                    display_phrase="floracore",
                    status="mapped",
                    occurrence_count=1,
                    examples=[],
                    candidate_keys=[candidate_key],
                    resolved_concept_id="cottagecore_dress",
                    reviewed_by="test-curator",
                    reviewed_at=reviewed_at,
                    first_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    last_seen_at=reviewed_at,
                ),
                FashionConceptProposal(
                    normalized_phrase="quiltoria",
                    display_phrase="quiltoria",
                    status="pending",
                    occurrence_count=1,
                    examples=[],
                    candidate_keys=[candidate_key],
                    first_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    last_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_observability_explains_ontology_mapping_and_product_safety(self):
        payload = build_scan_observability(self.db, self.run)

        self.assertEqual(payload["discovery"]["method"], "embedded_storefront_data")
        self.assertTrue(payload["discovery"]["fallback_used"])
        self.assertEqual(len(payload["discovery"]["attempts"]), 2)
        self.assertGreater(payload["ontology"]["recognized_signal_count"], 0)
        self.assertIn(
            "quiltoria",
            [
                item["phrase"]
                for item in payload["ontology"]["unrecognized_phrases"]
            ],
        )
        self.assertEqual(payload["rescoring"]["rescore_recommended_count"], 1)
        self.assertEqual(
            payload["mapping_change_warnings"][0]["phrase"],
            "floracore",
        )
        self.assertEqual(
            payload["mapping_change_warnings"][0]["published_candidate_ids"],
            [self.candidate.id],
        )
        self.assertEqual(
            payload["published_product_safety"]["active_published_count"],
            1,
        )
        self.assertFalse(
            payload["published_product_safety"]["published_products_changed"]
        )

    def test_explicit_rescore_clears_the_mapping_change_warning(self):
        self.candidate.scoring_analysis = {
            "scored_at": "2026-07-01T12:00:00+00:00",
            "rescored_at": "2026-07-03T12:00:00+00:00",
        }
        self.db.commit()

        payload = build_scan_observability(self.db, self.run)

        self.assertEqual(payload["mapping_change_warnings"], [])
        self.assertEqual(payload["rescoring"]["rescore_recommended_count"], 0)
        self.assertEqual(payload["rescoring"]["manually_rescored_count"], 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.curation.scoring as scoring_module
from app.curation.candidate_queue import approve_candidate
from app.curation.candidate_scoring import (
    assign_product_candidate_city,
    rescore_product_candidate,
)
from app.curation.city_assignment import (
    AUTO_ASSIGNED,
    MANUALLY_ASSIGNED,
    NEEDS_CITY_REVIEW,
    NO_STRONG_CITY_MATCH,
    CityScanMode,
    build_city_assignment_decision,
)
from app.curation.product_candidate_publisher import publish_product_candidate
from app.curation.scoring import (
    STRICT_COMPONENT_WEIGHTS,
    STRICT_DISTINCTIVENESS_SCORING_MODE,
    CityScoreDetail,
    ScoreResult,
)
from app.curation.shopify_collection import (
    CollectionScanOptions,
    score_candidate_for_scan,
)
from app.database import Base
from app.models import City, Country, Product, ProductCandidate
from app.routers.catalog_admin import CollectionScanRequest


def _city_detail(
    score: int,
    *,
    eligible: bool = True,
) -> CityScoreDetail:
    return CityScoreDetail(
        score=score,
        reasons=[f"Test score {score}"],
        confidence=90,
        component_scores={
            "visual_aesthetic": 8.5,
            "climate_practicality": 8.5,
            "lifestyle_occasion": 8.5,
            "distinctive_enhancement": 8.5,
        },
        component_points={
            "visual_aesthetic": 25.5,
            "climate_practicality": 21.25,
            "lifestyle_occasion": 17.0,
            "distinctive_enhancement": 21.25,
        },
        component_reasons={},
        tier="Excellent / Haroona Selection",
        is_haroona_selection=score >= 80 and eligible,
        assumptions=[],
        evidence_gaps=[],
        display_name="Test city",
        destination_type="city",
        scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
        scoring_version="strict_distinctiveness_v2",
        raw_total=score,
        city_fit_percentage=score,
        distinctiveness_score=21,
        primary_match_eligible=eligible,
        match_type="primary_match" if eligible else "broad_match",
    )


def _score_result(city_scores: list[tuple[str, int]]) -> ScoreResult:
    details = {
        city_slug: _city_detail(score)
        for city_slug, score in city_scores
    }
    target_slug, target_score = city_scores[0]
    return ScoreResult(
        score=target_score,
        reasons=details[target_slug].reasons,
        city_fit_scores={
            city_slug: score for city_slug, score in city_scores
        },
        confidence=90,
        recommended_city_slug=target_slug,
        destination_details=details,
        scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
        scoring_version="strict_distinctiveness_v2",
        raw_total=target_score,
        city_fit_percentage=target_score,
        distinctiveness_score=21,
        primary_match_eligible=True,
        match_type="primary_match",
    )


class AutoCityRequestAndScoringTests(unittest.TestCase):
    active_city_slugs = ("london", "new-york", "copenhagen")

    def _auto_options(self) -> CollectionScanOptions:
        return CollectionScanOptions(
            source_url="https://shop.example.com/collections/dresses",
            merchant_name="Example",
            target_city_slug=None,
            city_mode=CityScanMode.AUTO.value,
            active_city_slugs=self.active_city_slugs,
        )

    def test_auto_scan_request_succeeds_without_a_city(self):
        request = CollectionScanRequest(
            source_url="https://shop.example.com/collections/dresses",
            merchant_name="Example",
            city_mode="auto",
            target_city_slug=None,
        )

        score, assignment = score_candidate_for_scan(
            options=self._auto_options(),
            title="Architectural pleated cotton midi dress",
            description="A breathable sculptural dress for city walking.",
            product_type="Dress",
            tags=["pleated", "cotton"],
            normalized_category="dress",
            brand_name="Example",
        )

        self.assertEqual(request.city_mode, CityScanMode.AUTO)
        self.assertIsNone(request.target_city_slug)
        self.assertEqual(
            score.scoring_mode,
            STRICT_DISTINCTIVENESS_SCORING_MODE,
        )
        self.assertEqual(assignment.city_scan_mode, CityScanMode.AUTO.value)

    def test_selected_city_mode_still_requires_a_city(self):
        with self.assertRaises(ValidationError) as raised:
            CollectionScanRequest(
                source_url="https://shop.example.com/collections/dresses",
                merchant_name="Example",
                city_mode="selected",
                target_city_slug=None,
            )

        self.assertIn("target_city_slug is required", str(raised.exception))

    def test_existing_city_request_keeps_selected_scan_behavior(self):
        request = CollectionScanRequest(
            source_url="https://shop.example.com/collections/dresses",
            merchant_name="Example",
            target_city_slug="London",
        )
        options = CollectionScanOptions(
            source_url=request.source_url,
            merchant_name=request.merchant_name,
            target_city_slug=request.target_city_slug,
            city_mode=request.city_mode.value,
        )

        _, assignment = score_candidate_for_scan(
            options=options,
            title="Tailored wool midi dress",
            description="Structured wool dress for work and evening.",
            product_type="Dress",
            tags=["tailored", "wool"],
            normalized_category="dress",
            brand_name="Example",
        )

        self.assertEqual(request.city_mode, CityScanMode.SELECTED)
        self.assertEqual(request.target_city_slug, "london")
        self.assertEqual(assignment.final_city_slug, "london")
        self.assertEqual(assignment.city_assignment_source, "selected_scan")

    def test_invalid_explicit_auto_request_does_not_ignore_a_city(self):
        with self.assertRaises(ValidationError) as raised:
            CollectionScanRequest(
                source_url="https://shop.example.com/collections/dresses",
                merchant_name="Example",
                city_mode="auto",
                target_city_slug="london",
            )

        self.assertIn("must be omitted", str(raised.exception))

    def test_garment_facts_are_extracted_once_for_all_cities(self):
        with patch(
            "app.curation.scoring._extract_garment_facts",
            wraps=scoring_module._extract_garment_facts,
        ) as extract:
            score, _ = score_candidate_for_scan(
                options=self._auto_options(),
                title="Pleated technical cotton dress",
                description="Breathable cotton with modular pleated panels.",
                product_type="Dress",
                tags=["technical", "pleated"],
                normalized_category="dress",
                brand_name="Example",
            )

        self.assertEqual(extract.call_count, 1)
        self.assertEqual(
            set(score.destination_details or {}),
            set(self.active_city_slugs),
        )

    def test_auto_mode_scores_every_active_city_and_returns_ranked_winner(self):
        score, assignment = score_candidate_for_scan(
            options=self._auto_options(),
            title="Asymmetrical technical layered utility dress",
            description="Architectural modular panels in breathable cotton.",
            product_type="Dress",
            tags=["asymmetrical", "utility", "layered"],
            normalized_category="dress",
            brand_name="Example",
        )

        self.assertEqual(
            set(score.destination_details or {}),
            set(self.active_city_slugs),
        )
        self.assertEqual(
            assignment.recommended_city_slug,
            assignment.city_candidates[0]["city_slug"],
        )
        self.assertEqual(
            [item["rank"] for item in assignment.city_candidates],
            list(range(1, len(self.active_city_slugs) + 1)),
        )
        self.assertEqual(
            list(STRICT_COMPONENT_WEIGHTS.values()),
            [30, 25, 20, 25],
        )

    def test_strong_winner_is_automatically_assigned(self):
        decision = build_city_assignment_decision(
            _score_result(
                [("copenhagen", 86), ("new-york", 78), ("london", 75)]
            ),
            city_mode="auto",
            active_city_slugs=self.active_city_slugs,
        )

        self.assertEqual(decision.final_city_slug, "copenhagen")
        self.assertEqual(decision.city_assignment_status, AUTO_ASSIGNED)
        self.assertEqual(decision.city_score_margin, 8)

    def test_close_top_two_requires_city_review(self):
        decision = build_city_assignment_decision(
            _score_result(
                [("copenhagen", 86), ("new-york", 84), ("london", 75)]
            ),
            city_mode="auto",
            active_city_slugs=self.active_city_slugs,
        )

        self.assertIsNone(decision.final_city_slug)
        self.assertEqual(decision.city_assignment_status, NEEDS_CITY_REVIEW)
        self.assertEqual(decision.city_score_margin, 2)

    def test_score_below_80_has_no_strong_city_match(self):
        decision = build_city_assignment_decision(
            _score_result(
                [("new-york", 79), ("london", 74), ("copenhagen", 70)]
            ),
            city_mode="auto",
            active_city_slugs=self.active_city_slugs,
        )

        self.assertEqual(decision.recommended_city_slug, "new-york")
        self.assertIsNone(decision.final_city_slug)
        self.assertEqual(
            decision.city_assignment_status,
            NO_STRONG_CITY_MATCH,
        )


class AutoCityPersistenceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        country = Country(code="GB", name="United Kingdom")
        self.db.add(country)
        self.db.flush()
        for index, (slug, name) in enumerate(
            (
                ("london", "London"),
                ("new-york", "New York"),
                ("copenhagen", "Copenhagen"),
            )
        ):
            self.db.add(
                City(
                    slug=slug,
                    name=name,
                    country=country,
                    latitude=50 + index,
                    longitude=-1 - index,
                )
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _candidate(
        self,
        external_id: str,
        *,
        target_city_slug: str | None,
        review_status: str = "pending",
    ) -> ProductCandidate:
        candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url="https://shop.example.com/collections/dresses",
            merchant_name="Example",
            brand_name="Example",
            merchant_verification="unverified",
            external_product_id=external_id,
            title="Architectural pleated cotton midi dress",
            description="Breathable cotton with structured pleated panels.",
            price_amount=89,
            currency="USD",
            affiliate_url=f"https://tracking.example.com/{external_id}",
            merchant_url=f"https://shop.example.com/products/{external_id}",
            affiliate_link_status="verified",
            image_url=f"https://cdn.example.com/{external_id}.jpg",
            availability="in_stock",
            normalized_category="dress",
            city_scan_mode="auto",
            target_city_slug=target_city_slug,
            recommended_city_slug="copenhagen",
            recommended_city_score=86,
            runner_up_city_slug="new-york",
            runner_up_city_score=78,
            city_score_margin=8,
            city_assignment_status=(
                MANUALLY_ASSIGNED if target_city_slug else NEEDS_CITY_REVIEW
            ),
            city_assignment_source=(
                "manual_override" if target_city_slug else "automatic"
            ),
            manual_city_override=bool(target_city_slug),
            city_candidates=[],
            eligibility_status="eligible",
            eligibility_reasons=[],
            platform_alignment_score=8,
            platform_alignment_reasons=[],
            city_fit_score=86,
            city_fit_scores={"copenhagen": 86, "new-york": 78, "london": 75},
            secondary_city_slug="new-york",
            scoring_confidence=90,
            scoring_method="deterministic_rules",
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            scoring_version="strict_distinctiveness_v2",
            scoring_analysis={
                "primary_match_eligible": True,
                "gate_failure_reasons": [],
            },
            haroona_score=86,
            score_reasons=["Strong city fit"],
            review_status=review_status,
        )
        self.db.add(candidate)
        self.db.commit()
        return candidate

    def test_curator_can_override_an_automatic_recommendation(self):
        candidate = self._candidate("manual-override", target_city_slug=None)

        score = assign_product_candidate_city(
            self.db,
            candidate,
            target_city_slug="london",
            assigned_by="test-curator",
        )

        self.assertEqual(candidate.target_city_slug, "london")
        self.assertEqual(candidate.city_assignment_status, MANUALLY_ASSIGNED)
        self.assertEqual(candidate.city_assignment_source, "manual_override")
        self.assertTrue(candidate.manual_city_override)
        self.assertEqual(
            candidate.haroona_score,
            score.raw_total if score.raw_total is not None else score.score,
        )

    def test_manual_override_survives_normal_rescoring(self):
        candidate = self._candidate(
            "manual-rescore",
            target_city_slug="london",
        )

        rescore_product_candidate(
            self.db,
            candidate,
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            manual_observed_garment_details=["structured pleated panels"],
            rescored_by="test-curator",
        )

        self.assertEqual(candidate.target_city_slug, "london")
        self.assertEqual(candidate.city_assignment_status, MANUALLY_ASSIGNED)
        self.assertEqual(candidate.city_assignment_source, "manual_override")
        self.assertTrue(candidate.manual_city_override)

    def test_product_cannot_publish_without_a_final_city(self):
        candidate = self._candidate(
            "no-final-city",
            target_city_slug=None,
            review_status="approved",
        )

        with self.assertRaises(ValueError) as raised:
            publish_product_candidate(self.db, candidate)

        self.assertIn("final city", str(raised.exception))
        self.assertIsNone(candidate.promoted_product_id)

    def test_existing_approval_and_affiliate_publish_flow_still_works(self):
        candidate = self._candidate(
            "selected-flow",
            target_city_slug="london",
        )
        candidate.city_scan_mode = "selected"
        candidate.city_assignment_source = "selected_scan"
        candidate.manual_city_override = False
        candidate.scoring_mode = "legacy"
        candidate.scoring_version = "hybrid_v1_1"
        candidate.scoring_analysis = {}
        self.db.commit()

        approve_candidate(
            self.db,
            candidate,
            reviewed_by="test-curator",
        )
        result = publish_product_candidate(self.db, candidate)
        product = self.db.query(Product).filter(Product.id == result["product_id"]).one()

        self.assertEqual(candidate.review_status, "approved")
        self.assertEqual(candidate.affiliate_link_status, "verified")
        self.assertTrue(product.is_active)
        self.assertEqual(product.city.slug, "london")


if __name__ == "__main__":
    unittest.main()

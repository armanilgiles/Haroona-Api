import os
import unittest
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.candidate_scoring import rescore_product_candidate
from app.curation.scoring import (
    HAROONA_SELECTION_THRESHOLD,
    HYBRID_COMPONENT_WEIGHTS,
    HYBRID_SCORING_VERSION,
    LEGACY_SCORING_MODE,
    STRICT_COMPONENT_WEIGHTS,
    STRICT_DISTINCTIVENESS_SCORING_MODE,
    STRICT_DISTINCTIVENESS_SCORING_VERSION,
    evaluate_primary_match_gate,
    score_city_fit,
    scoring_profile_payload,
)
from app.curation.scoring_settings import (
    CITY_DISTINCTIVENESS_GATE_SETTING,
    get_curation_scoring_configuration,
    set_curation_scoring_configuration,
)
from app.database import Base
from app.models import ProductCandidate


class StrictDistinctivenessScoringTests(unittest.TestCase):
    def test_legacy_and_strict_profiles_keep_separate_weights_and_versions(self):
        legacy = scoring_profile_payload(LEGACY_SCORING_MODE)
        strict = scoring_profile_payload(STRICT_DISTINCTIVENESS_SCORING_MODE)

        self.assertEqual(
            legacy["rubric_weights"],
            {
                "visual_compatibility": 35,
                "climate_compatibility": 30,
                "lifestyle_compatibility": 20,
                "distinctiveness": 15,
            },
        )
        self.assertEqual(
            strict["rubric_weights"],
            {
                "visual_compatibility": 30,
                "climate_compatibility": 25,
                "lifestyle_compatibility": 20,
                "distinctiveness": 25,
            },
        )
        self.assertEqual(set(HYBRID_COMPONENT_WEIGHTS), set(STRICT_COMPONENT_WEIGHTS))
        self.assertEqual(legacy["scoring_version"], HYBRID_SCORING_VERSION)
        self.assertEqual(
            strict["scoring_version"],
            STRICT_DISTINCTIVENESS_SCORING_VERSION,
        )
        self.assertFalse(legacy["primary_match_gate_enabled"])
        self.assertTrue(strict["primary_match_gate_enabled"])

    def test_strong_city_fit_can_fail_primary_match(self):
        result = score_city_fit(
            title="Floral openwork crochet maxi dress",
            description=(
                "Floral openwork crochet maxi dress with a scalloped hem and "
                "lightweight cotton construction."
            ),
            product_type="Dress",
            normalized_category="dress",
            target_city_slug="greek-islands",
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
        )

        self.assertGreaterEqual(result.city_fit_percentage or 0, 80)
        self.assertFalse(result.primary_match_eligible)
        self.assertIn("marketing_language_primary", result.gate_failure_reasons)

    def test_distinctiveness_nine_fails_and_ten_requires_every_other_gate(self):
        eligible_at_nine, failures_at_nine = evaluate_primary_match_gate(
            raw_total=90,
            distinctiveness_score=9,
            observed_garment_details=["Scalloped crochet hem"],
            nearest_rival_test_passed=True,
            marketing_language_primary=False,
        )
        eligible_at_ten, failures_at_ten = evaluate_primary_match_gate(
            raw_total=90,
            distinctiveness_score=10,
            observed_garment_details=["Scalloped crochet hem"],
            nearest_rival_test_passed=True,
            marketing_language_primary=False,
        )

        self.assertFalse(eligible_at_nine)
        self.assertIn("distinctiveness_below_minimum", failures_at_nine)
        self.assertTrue(eligible_at_ten)
        self.assertEqual(failures_at_ten, ())

    def test_missing_or_marketing_only_observation_fails_gate(self):
        missing_eligible, missing_failures = evaluate_primary_match_gate(
            raw_total=90,
            distinctiveness_score=15,
            observed_garment_details=[],
            nearest_rival_test_passed=True,
            marketing_language_primary=False,
        )
        marketing_eligible, marketing_failures = evaluate_primary_match_gate(
            raw_total=90,
            distinctiveness_score=15,
            observed_garment_details=["Scalloped crochet hem"],
            nearest_rival_test_passed=True,
            marketing_language_primary=True,
        )

        self.assertFalse(missing_eligible)
        self.assertIn("observed_evidence_missing", missing_failures)
        self.assertFalse(marketing_eligible)
        self.assertIn("marketing_language_primary", marketing_failures)

    def test_manual_observation_can_satisfy_evidence_and_records_rival(self):
        observation = (
            "Tailored cotton trench coat with double-breasted construction, "
            "a belt, and a structured layerable silhouette."
        )
        result = score_city_fit(
            title="Kensington Tailored Trench",
            description=(
                "Tailored cotton trench coat double breasted belted structured "
                "layerable british heritage city day"
            ),
            product_type="Coat",
            normalized_category="outerwear",
            target_city_slug="london",
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            manual_observed_garment_details=[observation],
        )

        self.assertGreaterEqual(result.raw_total or 0, HAROONA_SELECTION_THRESHOLD)
        self.assertTrue(result.primary_match_eligible)
        self.assertEqual(result.gate_failure_reasons, ())
        self.assertIsNotNone(result.nearest_competing_city)
        self.assertNotEqual(result.nearest_competing_city, "london")
        self.assertTrue(
            any(
                evidence["source"] == "manual_curator_observation"
                for evidence in result.distinctiveness_evidence
            )
        )
        self.assertIn("This garment fits London because", result.comparative_reason or "")

    def test_failed_gate_preserves_real_raw_total(self):
        description = (
            "striped cotton reconstructed polo shirt dress color block polo "
            "collar mid sleeves graphic logo inspired by british heritage for "
            "smart casual city day"
        )
        result = score_city_fit(
            title="Reworked Rugby Reconstructed Polo Dress",
            description=description,
            product_type="Dress",
            normalized_category="dress",
            target_city_slug="london",
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            manual_observed_garment_details=[description],
        )
        detail = result.destination_details["london"]
        component_total = sum(
            (Decimal(str(value)) for value in detail.component_points.values()),
            Decimal("0"),
        )

        self.assertGreaterEqual(result.raw_total or 0, HAROONA_SELECTION_THRESHOLD)
        self.assertFalse(result.primary_match_eligible)
        self.assertIn("nearest_rival_test_failed", result.gate_failure_reasons)
        self.assertEqual(
            result.raw_total,
            int(component_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        )
        self.assertNotEqual(result.raw_total, 74)


class ScoringConfigurationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _legacy_candidate(self) -> ProductCandidate:
        candidate = ProductCandidate(
            source="test",
            source_type="collection",
            source_url="https://example.com/collections/coats",
            merchant_name="Example",
            external_product_id="legacy-1",
            title="Tailored Wool Coat",
            description="Camel wool coat, double breasted and structured.",
            image_url="https://example.com/coat.jpg",
            normalized_category="outerwear",
            target_city_slug="london",
            city_fit_score=84,
            city_fit_scores={"london": 84},
            scoring_version=HYBRID_SCORING_VERSION,
            scoring_mode=LEGACY_SCORING_MODE,
            scoring_analysis={},
            haroona_score=84,
            score_reasons=["legacy score"],
            review_status="approved",
            promoted_product_id=42,
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    @patch.dict(os.environ, {CITY_DISTINCTIVENESS_GATE_SETTING: "false"})
    def test_switching_flag_does_not_modify_legacy_or_published_state(self):
        candidate = self._legacy_candidate()
        before = (
            candidate.city_fit_score,
            candidate.haroona_score,
            candidate.scoring_version,
            candidate.review_status,
            candidate.promoted_product_id,
        )

        initial = get_curation_scoring_configuration(self.db)
        updated = set_curation_scoring_configuration(
            self.db,
            enabled=True,
            updated_by="test-curator",
        )
        self.db.refresh(candidate)

        self.assertEqual(initial.scoring_mode, LEGACY_SCORING_MODE)
        self.assertEqual(
            updated.scoring_mode,
            STRICT_DISTINCTIVENESS_SCORING_MODE,
        )
        self.assertEqual(
            updated.as_dict()["scoring_version"],
            STRICT_DISTINCTIVENESS_SCORING_VERSION,
        )
        self.assertEqual(
            (
                candidate.city_fit_score,
                candidate.haroona_score,
                candidate.scoring_version,
                candidate.review_status,
                candidate.promoted_product_id,
            ),
            before,
        )

    def test_explicit_rescore_versions_candidate_without_unpublishing(self):
        candidate = self._legacy_candidate()
        observation = (
            "Tailored wool double-breasted coat with a structured, layerable "
            "silhouette."
        )
        result = rescore_product_candidate(
            self.db,
            candidate,
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            manual_observed_garment_details=[observation],
            rescored_by="test-curator",
        )

        self.assertEqual(
            candidate.scoring_version,
            STRICT_DISTINCTIVENESS_SCORING_VERSION,
        )
        self.assertEqual(candidate.scoring_mode, STRICT_DISTINCTIVENESS_SCORING_MODE)
        self.assertEqual(candidate.review_status, "approved")
        self.assertEqual(candidate.promoted_product_id, 42)
        self.assertEqual(
            candidate.scoring_analysis["scoring_mode"],
            STRICT_DISTINCTIVENESS_SCORING_MODE,
        )
        self.assertEqual(candidate.haroona_score, result.raw_total)
        self.assertIn(observation, candidate.manual_observed_garment_details)


if __name__ == "__main__":
    unittest.main()

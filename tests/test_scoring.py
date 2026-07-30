import unittest
from decimal import Decimal, ROUND_HALF_UP

from app.curation.scoring import (
    HAROONA_SELECTION_THRESHOLD,
    HYBRID_COMPONENT_WEIGHTS,
    HYBRID_SCORING_VERSION,
    SUPPORTED_CITY_SLUGS,
    score_city_fit,
)


class CityFitScoringTests(unittest.TestCase):
    def test_unverified_merchant_name_cannot_apply_a_saved_profile(self):
        verified = score_city_fit(
            title="Smocked Long Dress in Black/White",
            product_type="Dress",
            target_city_slug="tokyo",
            normalized_category="dress",
            merchant_name="Nobody's Child",
            merchant_profile_allowed=True,
        )
        unverified = score_city_fit(
            title="Smocked Long Dress in Black/White",
            product_type="Dress",
            target_city_slug="tokyo",
            normalized_category="dress",
            merchant_name="Nobody's Child",
            merchant_profile_allowed=False,
        )

        self.assertIsNotNone(verified.merchant_profile_key)
        self.assertIsNone(unverified.merchant_profile_key)
        self.assertNotEqual(verified.score, unverified.score)

    def test_generic_smocked_dress_cannot_reach_strong_tokyo_fit(self):
        result = score_city_fit(
            title="Smocked Long Dress in Black/White Print",
            description="Rayon smocked bodice with elastic waist and flowy maxi skirt.",
            product_type="Dress",
            target_city_slug="tokyo",
            normalized_category="dress",
            merchant_name="shop.simon.com",
            merchant_profile_allowed=False,
        )

        self.assertGreaterEqual(result.score, 55)
        self.assertLess(result.score, HAROONA_SELECTION_THRESHOLD)
        self.assertEqual(set(result.city_fit_scores or {}), set(SUPPORTED_CITY_SLUGS))
        self.assertIsNotNone(result.secondary_city_slug)
        self.assertEqual(result.scoring_version, HYBRID_SCORING_VERSION)

    def test_distinctive_tokyo_evidence_can_earn_a_haroona_selection(self):
        result = score_city_fit(
            title="Asymmetrical Deconstructed Technical Layered Cargo Jacket",
            description="Architectural utility construction with modular panels and breathable cotton.",
            product_type="Jacket",
            target_city_slug="tokyo",
            normalized_category="tops",
            occasion="city commuting",
        )

        self.assertGreaterEqual(result.score, HAROONA_SELECTION_THRESHOLD)
        self.assertGreaterEqual(result.confidence or 0, 70)
        self.assertEqual(result.recommended_city_slug, "tokyo")
        self.assertTrue(result.destination_details["tokyo"].is_haroona_selection)

    def test_hybrid_total_is_derived_from_the_four_weighted_components(self):
        result = score_city_fit(
            title="Dolly Cowl Neck Halter Dress",
            description="Black cowl neck halter style with an open back and fluid lightweight silhouette.",
            product_type="Dress",
            target_city_slug="greek-islands",
            normalized_category="dress",
            merchant_name="Nobody's Child",
        )
        detail = result.destination_details["greek-islands"]
        total = sum(
            (Decimal(str(value)) for value in detail.component_points.values()),
            Decimal("0"),
        )

        self.assertEqual(set(detail.component_scores), set(HYBRID_COMPONENT_WEIGHTS))
        self.assertEqual(
            result.score,
            int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        )
        self.assertGreaterEqual(result.score, 82)
        self.assertLessEqual(result.score, 90)
        self.assertEqual(result.recommended_city_slug, "greek-islands")

    def test_dolly_comparison_is_calibrated_without_inflating_every_city(self):
        result = score_city_fit(
            title="Dolly Cowl Neck Halter Dress",
            description="Black cowl neck halter style with an open back and fluid lightweight silhouette.",
            product_type="Dress",
            target_city_slug="los-angeles",
            normalized_category="dress",
            merchant_name="Nobody's Child",
        )
        scores = result.city_fit_scores or {}

        self.assertGreaterEqual(scores["greek-islands"], 84)
        self.assertGreaterEqual(scores["sydney"], 78)
        self.assertGreaterEqual(scores["los-angeles"], HAROONA_SELECTION_THRESHOLD)
        self.assertGreater(scores["greek-islands"], scores["tokyo"])
        self.assertLess(scores["tokyo"], HAROONA_SELECTION_THRESHOLD)

    def test_romantic_midi_prefers_provence_but_keeps_tuscany_strong(self):
        result = score_city_fit(
            title="Avery Midi Dress",
            description=(
                "Black floral print with puff sleeves, square neck, shirred bodice "
                "and tiered lightweight viscose skirt."
            ),
            product_type="Dress",
            target_city_slug="provence",
            normalized_category="dress",
            merchant_name="Nobody's Child",
        )
        scores = result.city_fit_scores or {}

        self.assertEqual(result.recommended_city_slug, "provence")
        self.assertGreaterEqual(scores["provence"], HAROONA_SELECTION_THRESHOLD)
        self.assertLessEqual(scores["provence"], 92)
        self.assertGreaterEqual(scores["tuscany"], 75)
        self.assertLess(scores["tokyo"], 70)

    def test_unknown_material_caps_climate_confidence_instead_of_guessing(self):
        result = score_city_fit(
            title="Black Halter Dress",
            description="Open back with a fluid silhouette; likely lightweight fabric.",
            target_city_slug="greek-islands",
            normalized_category="dress",
        )
        detail = result.destination_details["greek-islands"]

        self.assertLessEqual(detail.component_scores["climate_practicality"], 8.0)
        self.assertLessEqual(detail.confidence, 75)
        self.assertIn("Material not confirmed", detail.evidence_gaps)


if __name__ == "__main__":
    unittest.main()

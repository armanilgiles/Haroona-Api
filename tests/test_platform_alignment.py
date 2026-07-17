import unittest

from app.curation.platform_alignment import (
    PLATFORM_ALIGNMENT_THRESHOLD,
    platform_alignment_passes,
    score_platform_alignment,
)


class PlatformAlignmentTests(unittest.TestCase):
    def _score(self, **overrides):
        values = {
            "title": "Smocked Long Dress in Black/White",
            "description": "A rayon dress with an elastic waist and smocked bodice.",
            "product_type": "Dress",
            "tags": ["print"],
            "merchant_name": "shop.simon.com",
            "brand_name": "2244",
            "merchant_verification": "unverified",
            "image_url": "https://cdn.example.com/dress.jpg",
            "image_quality_score": 70,
            "normalized_category": "dress",
            "city_fit_score": 55,
        }
        values.update(overrides)
        return score_platform_alignment(**values)

    def test_unknown_mass_market_dress_falls_below_platform_threshold(self):
        result = self._score()

        self.assertLess(result.score, PLATFORM_ALIGNMENT_THRESHOLD)
        self.assertFalse(result.passes)
        self.assertFalse(platform_alignment_passes(result.score))

    def test_recognized_editorial_brand_can_pass_without_merchant_profile_leakage(self):
        result = self._score(
            title="Diane von Furstenberg Tailored Silk Wrap Dress",
            description="A structured silk wrap dress with a refined drape.",
            brand_name="Diane von Furstenberg",
            city_fit_score=68,
            image_quality_score=82,
        )

        self.assertGreaterEqual(result.score, PLATFORM_ALIGNMENT_THRESHOLD)
        self.assertTrue(result.passes)
        self.assertTrue(any("recognized brand" in reason for reason in result.reasons))

    def test_recognizable_brand_in_marketplace_title_is_not_treated_as_anonymous(self):
        result = self._score(
            title="Burberry Ladies Optical Dress",
            description="Pleated silk dress with an intentional silhouette.",
            brand_name="4022",
            city_fit_score=82,
            image_quality_score=82,
        )

        self.assertGreaterEqual(result.score, PLATFORM_ALIGNMENT_THRESHOLD)
        self.assertTrue(any("recognized brand: burberry" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()

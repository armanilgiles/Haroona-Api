import unittest

from app.curation.scoring import score_city_fit


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
        self.assertFalse(
            any(reason.startswith("merchant ") for reason in unverified.reasons)
        )


if __name__ == "__main__":
    unittest.main()

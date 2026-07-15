import unittest

from app.curation.eligibility import (
    ELIGIBLE,
    INELIGIBLE,
    NEEDS_REVIEW,
    evaluate_candidate_eligibility,
)


class CandidateEligibilityTests(unittest.TestCase):
    def _evaluate(self, **overrides):
        values = {
            "title": "Linen Midi Dress",
            "affiliate_url": None,
            "merchant_url": "https://shop.example.com/products/linen-midi",
            "image_url": "https://cdn.example.com/linen-midi.jpg",
            "availability": "in_stock",
            "normalized_category": "dress",
            "price_amount": "89.00",
            "currency": "USD",
        }
        values.update(overrides)
        return evaluate_candidate_eligibility(**values)

    def test_complete_candidate_is_eligible(self):
        result = self._evaluate()

        self.assertEqual(result.status, ELIGIBLE)
        self.assertEqual(result.reasons, [])

    def test_missing_price_is_repairable_review_warning(self):
        result = self._evaluate(price_amount=None)

        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertEqual(result.blocking_reasons, [])
        self.assertEqual(result.warning_reasons, ["missing_price"])

    def test_stock_category_url_and_image_are_hard_gates(self):
        result = self._evaluate(
            affiliate_url=None,
            merchant_url=None,
            image_url=None,
            availability="out of stock",
            normalized_category=None,
        )

        self.assertEqual(result.status, INELIGIBLE)
        self.assertEqual(
            result.blocking_reasons,
            ["missing_product_url", "out_of_stock", "missing_category", "missing_image"],
        )


if __name__ == "__main__":
    unittest.main()

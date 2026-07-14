import unittest

from app.curation.source_scan_guardrails import (
    get_scanner_image_capabilities,
    get_merchant_source_guidance,
    normalize_category_hint,
)


class SourceScanGuardrailTests(unittest.TestCase):
    def test_category_aliases_are_normalized(self):
        self.assertEqual(normalize_category_hint(" Dresses "), "dress")
        self.assertEqual(normalize_category_hint("sets"), "co-ords")
        self.assertEqual(normalize_category_hint("Footwear"), "shoes")
        self.assertIsNone(normalize_category_hint("auto-detect"))

    def test_unknown_category_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported fallback category"):
            normalize_category_hint("random-category")

    def test_known_merchant_alias_is_resolved_to_canonical_name(self):
        guidance = get_merchant_source_guidance(
            "https://www.nobodyschild.com/en-us/collections/materra",
            "nobodys child",
        )

        self.assertEqual(guidance.verification, "verified")
        self.assertEqual(guidance.resolved_name, "Nobody's Child")

    def test_known_domain_conflict_is_reported(self):
        guidance = get_merchant_source_guidance(
            "https://www.nobodyschild.com/en-us/collections/materra",
            "LILYSILK",
        )

        self.assertEqual(guidance.verification, "conflict")
        self.assertEqual(guidance.suggested_name, "Nobody's Child")

    def test_unknown_domain_remains_allowed_but_unverified(self):
        guidance = get_merchant_source_guidance(
            "https://example-boutique.com/collections/new",
            "Example Boutique",
        )

        self.assertEqual(guidance.verification, "unverified")
        self.assertEqual(guidance.resolved_name, "Example Boutique")

    def test_shopify_reports_all_image_modes(self):
        supported_modes, default_mode = get_scanner_image_capabilities(
            "shopify_collection"
        )

        self.assertEqual(
            supported_modes,
            ("fast", "smart", "model_only"),
        )
        self.assertEqual(default_mode, "smart")

    def test_shopcider_reports_all_image_modes(self):
        supported_modes, default_mode = get_scanner_image_capabilities(
            "shopcider_category"
        )

        self.assertEqual(
            supported_modes,
            ("fast", "smart", "model_only"),
        )
        self.assertEqual(default_mode, "smart")


if __name__ == "__main__":
    unittest.main()

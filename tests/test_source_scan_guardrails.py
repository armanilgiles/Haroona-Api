import unittest

from app.curation.source_scan_guardrails import (
    get_scanner_image_capabilities,
    get_merchant_source_guidance,
    normalize_category_hint,
)
from app.curation.scanner_registry import (
    UnsupportedScannerError,
    detect_curation_scanner,
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

    def test_unknown_domain_cannot_claim_a_known_merchant_profile(self):
        guidance = get_merchant_source_guidance(
            "https://shop.simon.com/collections/women-clothing-dresses",
            "Nobody's Child",
        )

        self.assertEqual(guidance.verification, "conflict")
        self.assertEqual(guidance.suggested_name, "shop.simon.com")
        self.assertIn("nobodyschild.com", guidance.message or "")

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

    def test_generic_public_storefront_uses_catch_all_scanner(self):
        scanner = detect_curation_scanner(
            "https://example-boutique.com/category/summer-dresses"
        )

        self.assertEqual(scanner.name, "generic_storefront")
        self.assertEqual(scanner.source, "storefront")
        self.assertEqual(
            scanner.supported_image_modes,
            ("fast", "smart", "model_only"),
        )

    def test_private_network_storefront_is_rejected(self):
        with self.assertRaises(UnsupportedScannerError):
            detect_curation_scanner("http://127.0.0.1:8000/collections/private")

    def test_lilysilk_reports_fast_and_smart_image_modes(self):
        supported_modes, default_mode = get_scanner_image_capabilities(
            "lilysilk_category"
        )

        self.assertEqual(supported_modes, ("fast", "smart"))
        self.assertEqual(default_mode, "smart")


if __name__ == "__main__":
    unittest.main()

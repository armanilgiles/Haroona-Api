import unittest

from app.curation.fashion_ontology import (
    calibration_garments,
    load_fashion_ontology,
    ontology_counts,
    recognize_fashion_evidence,
)
from app.curation.scoring import score_city_fit


class FashionOntologyTests(unittest.TestCase):
    def test_required_catalog_counts_and_unique_identifiers(self):
        ontology = load_fashion_ontology()
        counts = ontology_counts()
        concepts = ontology["concepts"]
        brands = ontology["brands"]

        self.assertEqual(counts["canonical_concepts"], 400)
        self.assertEqual(counts["aliases_and_related_phrases"], 2_000)
        self.assertEqual(counts["calibration_garments"], 100)
        self.assertEqual(len({item["id"] for item in concepts}), 400)
        self.assertEqual(len({item["key"] for item in brands}), len(brands))
        self.assertTrue(all(len(item["aliases"]) == 5 for item in concepts))

    def test_related_concepts_expand_literal_product_language(self):
        evidence = recognize_fashion_evidence(
            "Burberry striped cotton reconstructed polo shirt dress",
            brand_name="Burberry",
        )

        self.assertIn("preppy", evidence.traits)
        self.assertIn("british_heritage", evidence.traits)
        self.assertIn("graphic", evidence.traits)
        self.assertEqual(evidence.brand.origin, "london")

    def test_all_calibration_ranges_pass(self):
        checked = 0
        for garment in calibration_garments():
            for destination_slug, expected_range in garment[
                "expected_ranges"
            ].items():
                result = score_city_fit(
                    title=garment["title"],
                    description=garment["description"],
                    target_city_slug=destination_slug,
                    normalized_category=garment["normalized_category"],
                    brand_name=garment.get("brand_name"),
                )
                lower, upper = expected_range
                self.assertGreaterEqual(
                    result.score,
                    lower,
                    f"{garment['id']} in {destination_slug}",
                )
                self.assertLessEqual(
                    result.score,
                    upper,
                    f"{garment['id']} in {destination_slug}",
                )
                checked += 1

        self.assertEqual(checked, 300)


if __name__ == "__main__":
    unittest.main()

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.concept_learning import (
    create_concept_from_proposal,
    extract_unknown_concept_phrases,
    load_runtime_concept_overrides,
    map_proposal_to_concept,
    record_unknown_concepts_for_scan,
    reject_concept_proposal,
)
from app.curation.fashion_ontology import recognize_fashion_evidence
from app.database import Base
from app.models import FashionConceptProposal, ProductCandidate


class ConceptLearningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        # Production uses autoflush=False. Keep this test session equivalent so
        # same-transaction uniqueness bugs are reproducible here.
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _proposal(self, phrase: str) -> FashionConceptProposal:
        row = FashionConceptProposal(
            normalized_phrase=phrase,
            display_phrase=phrase,
            status="pending",
            occurrence_count=1,
            examples=[],
            candidate_keys=[f"test:{phrase}"],
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def test_unknown_extraction_ignores_existing_related_phrases(self):
        phrases = extract_unknown_concept_phrases(
            "Burberry striped cotton reconstructed polo shirt dress",
            brand_name="Burberry",
        )
        self.assertNotIn("polo", phrases)
        self.assertNotIn("cotton", phrases)

    def test_mapping_requires_review_and_affects_future_recognition(self):
        proposal = self._proposal("campuscore")
        resolved = map_proposal_to_concept(
            self.db,
            proposal.id,
            concept_id="preppy",
            reviewed_by="test-curator",
        )
        self.assertEqual(resolved.status, "mapped")

        evidence = recognize_fashion_evidence(
            "A campuscore pleated skirt",
            concept_overrides=load_runtime_concept_overrides(self.db),
        )
        self.assertIn("preppy", evidence.concept_ids)

    def test_custom_concept_is_created_only_after_review(self):
        proposal = self._proposal("neoheritage")
        resolved = create_concept_from_proposal(
            self.db,
            proposal.id,
            label="Neo Heritage",
            category="aesthetic",
            traits=["preppy", "heritage"],
            reviewed_by="test-curator",
        )
        self.assertEqual(resolved.status, "created")

        evidence = recognize_fashion_evidence(
            "Neoheritage tailoring",
            concept_overrides=load_runtime_concept_overrides(self.db),
        )
        self.assertIn("neo_heritage", evidence.concept_ids)
        self.assertIn("preppy", evidence.traits)

    def test_rejection_never_creates_a_runtime_alias(self):
        proposal = self._proposal("catalognoise")
        resolved = reject_concept_proposal(
            self.db,
            proposal.id,
            reviewed_by="test-curator",
        )
        self.assertEqual(resolved.status, "rejected")
        self.assertEqual(load_runtime_concept_overrides(self.db), ())

    def test_scan_aggregates_duplicate_unknown_phrases_before_insert(self):
        for external_id, adjective in (("one", "Printed"), ("two", "Embellished")):
            self.db.add(
                ProductCandidate(
                    source="shopify",
                    source_type="collection",
                    source_url="https://example.com/collections/dresses",
                    scan_run_id="scan_duplicate_phrase",
                    merchant_name="Example Store",
                    brand_name="Teri Jon",
                    external_product_id=external_id,
                    title=f"Teri Jon by Rickie Freeman {adjective} Maxi Dress",
                    target_city_slug="london",
                    city_fit_score=0,
                    haroona_score=0,
                )
            )
        self.db.commit()

        result = record_unknown_concepts_for_scan(
            self.db,
            "scan_duplicate_phrase",
        )

        rows = (
            self.db.query(FashionConceptProposal)
            .filter(FashionConceptProposal.normalized_phrase == "rickie")
            .all()
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].occurrence_count, 2)
        self.assertEqual(len(rows[0].candidate_keys), 2)
        self.assertGreaterEqual(result["detected"], 2)


if __name__ == "__main__":
    unittest.main()

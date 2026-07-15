import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.scan_runs import (
    apply_scan_run_candidate_filter,
    complete_scan_run,
    fail_scan_run,
    scan_run_payload,
    start_scan_run,
    update_scan_run_context,
)
from app.database import Base
from app.models import CurationScanRunCandidate, ProductCandidate


class ScanRunTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _start_run(self, scan_run_id: str = "scan_test"):
        return start_scan_run(
            self.db,
            scan_run_id=scan_run_id,
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            target_city_slug="london",
            normalized_category="dress",
            requested_image_mode="smart",
            requested_limit=25,
        )

    def _candidate(self, scan_run_id: str = "scan_test") -> ProductCandidate:
        candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url="https://shop.example.com/collections/new",
            scan_run_id=scan_run_id,
            merchant_name="Example",
            external_product_id="product-1",
            title="City Dress",
            target_city_slug="london",
            haroona_score=92,
            score_reasons=[],
            review_status="pending",
        )
        self.db.add(candidate)
        self.db.commit()
        return candidate

    def test_completed_run_keeps_membership_after_candidate_is_rescanned(self):
        run = self._start_run()
        update_scan_run_context(
            self.db,
            run,
            merchant_name="Example",
            scanner_name="shopify_collection",
            source="shopify",
            source_type="collection",
            merchant_verification="unverified",
            effective_image_mode="smart",
        )
        candidate = self._candidate()

        complete_scan_run(
            self.db,
            run,
            result={
                "found": 1,
                "created": 1,
                "updated": 0,
                "items": [{"external_product_id": "product-1"}],
                "summary": {
                    "discovered": 12,
                    "selected_for_review": 1,
                    "saved": 1,
                    "created": 1,
                    "updated": 0,
                    "skipped_total": 11,
                },
            },
            warnings=["Source identity is unverified."],
        )

        candidate.scan_run_id = "scan_later"
        self.db.commit()
        old_run_rows = apply_scan_run_candidate_filter(
            self.db.query(ProductCandidate),
            "scan_test",
        ).all()

        self.db.refresh(run)
        membership_count = self.db.query(CurationScanRunCandidate).count()
        payload = scan_run_payload(run, candidate_count=membership_count)
        self.assertEqual([row.id for row in old_run_rows], [candidate.id])
        self.assertEqual(run.status, "completed")
        self.assertEqual(payload["discovered"], 12)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["warnings"], ["Source identity is unverified."])

    def test_failed_run_records_error_and_completion_time(self):
        run = self._start_run("scan_failed")

        fail_scan_run(
            self.db,
            run.id,
            error_message="Collection endpoint returned 404",
        )

        self.db.refresh(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "Collection endpoint returned 404")
        self.assertIsNotNone(run.completed_at)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.scan_runs import (
    apply_scanned_candidate_filter,
    apply_scan_run_candidate_filter,
    apply_store_candidate_filter,
    complete_scan_run,
    fail_scan_run,
    list_scanned_stores,
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

    def _start_run(
        self,
        scan_run_id: str = "scan_test",
        *,
        source_url: str = "https://shop.example.com/collections/new",
        merchant_name: str = "Example",
        target_city_slug: str = "london",
    ):
        return start_scan_run(
            self.db,
            scan_run_id=scan_run_id,
            source_url=source_url,
            merchant_name=merchant_name,
            target_city_slug=target_city_slug,
            normalized_category="dress",
            requested_image_mode="smart",
            requested_limit=25,
        )

    def _candidate(
        self,
        scan_run_id: str = "scan_test",
        *,
        external_product_id: str = "product-1",
        source_url: str = "https://shop.example.com/collections/new",
        merchant_name: str = "Example",
        review_status: str = "pending",
    ) -> ProductCandidate:
        candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url=source_url,
            scan_run_id=scan_run_id,
            merchant_name=merchant_name,
            external_product_id=external_product_id,
            title="City Dress",
            target_city_slug="london",
            haroona_score=92,
            score_reasons=[],
            review_status=review_status,
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

    def test_scanned_stores_group_www_aliases_and_keep_latest_details(self):
        older = self._start_run(
            "scan_older",
            source_url="https://www.example.com/collections/sale",
            merchant_name="Old Example Name",
            target_city_slug="paris",
        )
        older.started_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        complete_scan_run(self.db, older, result={}, warnings=[])

        latest = self._start_run(
            "scan_latest",
            source_url="https://example.com/collections/new",
            merchant_name="Example",
            target_city_slug="london",
        )
        latest.started_at = datetime(2026, 7, 2, tzinfo=timezone.utc)
        complete_scan_run(self.db, latest, result={}, warnings=[])

        stores = list_scanned_stores(self.db)

        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0]["store_key"], "example.com")
        self.assertEqual(stores[0]["merchant_name"], "Example")
        self.assertEqual(stores[0]["latest_scan_run_id"], "scan_latest")
        self.assertEqual(stores[0]["scan_count"], 2)
        self.assertEqual(stores[0]["city_slugs"], ["london", "paris"])

    def test_store_filter_spans_completed_runs_for_the_same_domain(self):
        first_run = self._start_run(
            "scan_first",
            source_url="https://www.example.com/collections/one",
        )
        update_scan_run_context(
            self.db,
            first_run,
            merchant_name="Example",
            scanner_name="shopify_collection",
            source="shopify",
            source_type="collection",
            merchant_verification="verified",
            effective_image_mode="smart",
        )
        first = self._candidate(
            "scan_first",
            external_product_id="product-first",
            source_url="https://www.example.com/collections/one",
        )
        complete_scan_run(
            self.db,
            first_run,
            result={"items": [{"external_product_id": "product-first"}]},
            warnings=[],
        )

        second_run = self._start_run(
            "scan_second",
            source_url="https://example.com/collections/two",
        )
        update_scan_run_context(
            self.db,
            second_run,
            merchant_name="Example",
            scanner_name="shopify_collection",
            source="shopify",
            source_type="collection",
            merchant_verification="verified",
            effective_image_mode="smart",
        )
        second = self._candidate(
            "scan_second",
            external_product_id="product-second",
            source_url="https://example.com/collections/two",
        )
        complete_scan_run(
            self.db,
            second_run,
            result={"items": [{"external_product_id": "product-second"}]},
            warnings=[],
        )

        other_run = self._start_run(
            "scan_other",
            source_url="https://other.example/collections/new",
            merchant_name="Other",
        )
        update_scan_run_context(
            self.db,
            other_run,
            merchant_name="Other",
            scanner_name="shopify_collection",
            source="shopify",
            source_type="collection",
            merchant_verification="verified",
            effective_image_mode="smart",
        )
        other = self._candidate(
            "scan_other",
            external_product_id="product-other",
            source_url="https://other.example/collections/new",
            merchant_name="Other",
        )
        complete_scan_run(
            self.db,
            other_run,
            result={"items": [{"external_product_id": "product-other"}]},
            warnings=[],
        )

        rows = apply_store_candidate_filter(
            self.db.query(ProductCandidate).order_by(ProductCandidate.id),
            "www.example.com",
        ).all()

        self.assertEqual([row.id for row in rows], [first.id, second.id])
        self.assertNotIn(other.id, [row.id for row in rows])

        legacy = self._candidate(
            "legacy",
            external_product_id="product-legacy",
            source_url="https://legacy.example/collections/new",
            merchant_name="Legacy",
        )
        scanned_rows = apply_scanned_candidate_filter(
            self.db.query(ProductCandidate).order_by(ProductCandidate.id),
        ).all()

        self.assertEqual(
            [row.id for row in scanned_rows],
            [first.id, second.id, other.id],
        )
        self.assertNotIn(legacy.id, [row.id for row in scanned_rows])


if __name__ == "__main__":
    unittest.main()

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.merchant_collections import (
    collection_payload,
    infer_collection_category,
    import_collection_records,
    load_collection_seed,
    normalize_collection_url,
)
from app.curation.scan_runs import complete_scan_run, start_scan_run
from app.curation.source_scan_guardrails import normalize_category_hint
from app.database import Base
from app.models import Merchant, MerchantCollection, Product
from app.routers.catalog_admin import (
    list_merchant_collections,
    list_merchants,
)


def record(
    *,
    merchant_name: str = "Farm Rio",
    domain: str = "farmrio.com",
    url: str = "https://farmrio.com/collections/dresses",
    name: str = "Dresses",
    category: str | None = "dress",
    status: str = "valid",
) -> dict:
    return {
        "merchant_name": merchant_name,
        "domain": domain,
        "collection_name": name,
        "collection_url": url,
        "category": category,
        "city": None,
        "is_active": True,
        "validation_status": status,
    }


class MerchantCollectionImportTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_imports_new_merchant_with_multiple_collections(self):
        report = import_collection_records(
            self.db,
            [
                record(),
                record(
                    url="https://farmrio.com/collections/tops",
                    name="Tops",
                    category="tops",
                ),
            ],
        )

        self.assertEqual(report["new_merchants_created"], 1)
        self.assertEqual(report["new_collections_created"], 2)
        self.assertEqual(self.db.query(Merchant).count(), 1)
        self.assertEqual(self.db.query(MerchantCollection).count(), 2)

    def test_rerun_is_idempotent_and_reuses_case_normalized_merchant(self):
        first = import_collection_records(self.db, [record()])
        second = import_collection_records(
            self.db,
            [
                record(
                    merchant_name="  FARM   RIO ",
                    domain="www.farmrio.com",
                )
            ],
        )

        self.assertEqual(first["new_collections_created"], 1)
        self.assertEqual(second["new_merchants_created"], 0)
        self.assertEqual(second["existing_merchants_reused"], 1)
        self.assertEqual(second["existing_collections_reused"], 1)
        self.assertEqual(self.db.query(Merchant).count(), 1)
        self.assertEqual(self.db.query(MerchantCollection).count(), 1)

    def test_duplicate_and_invalid_urls_are_reported_without_deleting_products(self):
        existing_product = Product(
            external_id="existing-1",
            source="manual",
            name="Existing Dress",
            currency="USD",
            brand_id=1,
            is_active=True,
        )
        self.db.add(existing_product)
        self.db.commit()

        report = import_collection_records(
            self.db,
            [
                record(),
                record(),
                record(url="not a valid domain", name="Invalid"),
            ],
        )

        self.assertEqual(report["duplicate_records_skipped"], 1)
        self.assertEqual(report["invalid_urls"], 1)
        self.assertEqual(self.db.query(Product).count(), 1)
        self.assertEqual(self.db.query(Product).first().name, "Existing Dress")

    def test_full_seed_counts_actual_workbook_records(self):
        seed = load_collection_seed()
        report = import_collection_records(self.db, seed["records"])

        self.assertEqual(report["total_input_records"], 352)
        self.assertEqual(report["new_merchants_created"], 36)
        self.assertEqual(report["new_collections_created"], 334)
        self.assertEqual(report["duplicate_records_skipped"], 10)
        self.assertEqual(report["records_requiring_manual_review"], 8)
        self.assertEqual(report["invalid_urls"], 0)

    def test_collection_url_normalization_removes_tracking_only(self):
        normalized, issues = normalize_collection_url(
            "loft.com/clothing/dresses/catl000013/?"
            "ipid=home&pf_t_fit=fit%3AShirtdress"
        )

        self.assertEqual(
            normalized,
            "https://loft.com/clothing/dresses/catl000013"
            "?pf_t_fit=fit%3AShirtdress",
        )
        self.assertIn("scheme_added", issues)
        self.assertIn("tracking_parameters_removed", issues)

    def test_import_links_matching_historical_scan_without_rewriting_it(self):
        historical = start_scan_run(
            self.db,
            scan_run_id="scan_historical",
            source_url="https://www.farmrio.com/collections/dresses?utm_source=old",
            merchant_name="Farm Rio",
            target_city_slug="new-york",
            normalized_category="dress",
            requested_image_mode="smart",
            requested_limit=25,
        )

        report = import_collection_records(self.db, [record()])

        self.db.refresh(historical)
        collection = self.db.query(MerchantCollection).one()
        self.assertEqual(report["historical_scan_runs_linked"], 1)
        self.assertEqual(historical.collection_id, collection.id)
        self.assertEqual(historical.source_url, "https://www.farmrio.com/collections/dresses?utm_source=old")

    def test_new_canonical_categories_and_seasonal_names(self):
        self.assertEqual(normalize_category_hint("activewear"), "activewear")
        self.assertEqual(
            normalize_category_hint("sweaters"),
            "sweaters_knitwear",
        )
        self.assertEqual(
            normalize_category_hint("cardigans"),
            "sweaters_knitwear",
        )
        self.assertEqual(normalize_category_hint("coats"), "outerwear")
        self.assertEqual(normalize_category_hint("jackets"), "outerwear")
        self.assertEqual(
            infer_collection_category(
                collection_name="Sweaters",
                normalized_url="https://example.com/collections/cardigans",
            ),
            "sweaters_knitwear",
        )
        self.assertEqual(
            infer_collection_category(
                collection_name="Coats & Jackets",
                normalized_url="https://example.com/collections/winter-outerwear",
            ),
            "outerwear",
        )
        self.assertIsNone(
            infer_collection_category(
                collection_name="Winter Edit",
                normalized_url="https://example.com/collections/winter",
            )
        )

        import_collection_records(
            self.db,
            [
                record(
                    url="https://farmrio.com/collections/fall-edit",
                    name="Fall Edit",
                    category=None,
                )
            ],
        )
        collection = self.db.query(MerchantCollection).one()
        self.assertEqual(collection.collection_name, "Fall Edit")
        self.assertIsNone(collection.canonical_category)

    def test_merchants_search_by_name_domain_and_collection(self):
        import_collection_records(
            self.db,
            [
                record(),
                record(
                    merchant_name="Lucky Brand",
                    domain="luckybrand.com",
                    url="https://luckybrand.com/women/clothing/shirts",
                    name="Graphic Shirts",
                    category="tops",
                ),
            ],
        )

        common = {
            "category": None,
            "city": None,
            "active": "all",
            "collection_active": "all",
            "scan_status": "all",
            "has_products": None,
            "limit": 50,
            "offset": 0,
            "db": self.db,
        }
        by_name = list_merchants(search="lucky", **common)
        by_domain = list_merchants(search="farmrio.com", **common)
        by_collection = list_merchants(search="graphic shirts", **common)

        self.assertEqual(by_name["items"][0]["name"], "Lucky Brand")
        self.assertEqual(by_domain["items"][0]["name"], "Farm Rio")
        self.assertEqual(by_collection["items"][0]["name"], "Lucky Brand")

    def test_collections_filter_by_category_and_latest_scan_status(self):
        import_collection_records(
            self.db,
            [
                record(),
                record(
                    url="https://farmrio.com/collections/tops",
                    name="Tops",
                    category="tops",
                ),
            ],
        )
        dresses = (
            self.db.query(MerchantCollection)
            .filter(MerchantCollection.canonical_category == "dress")
            .one()
        )
        run = start_scan_run(
            self.db,
            scan_run_id="scan_catalog",
            source_url=dresses.collection_url,
            merchant_name="Farm Rio",
            target_city_slug="new-york",
            normalized_category="dress",
            requested_image_mode="smart",
            requested_limit=25,
            collection_id=dresses.id,
        )
        complete_scan_run(
            self.db,
            run,
            result={
                "found": 12,
                "summary": {
                    "discovered": 12,
                    "saved": 3,
                    "message": "Saved three products",
                },
            },
            warnings=[],
        )

        completed = list_merchant_collections(
            merchant_id=dresses.merchant_id,
            search=None,
            category="dress",
            city=None,
            active="all",
            scan_status="completed",
            has_products=True,
            limit=100,
            offset=0,
            db=self.db,
        )
        never_scanned = list_merchant_collections(
            merchant_id=dresses.merchant_id,
            search=None,
            category="tops",
            city=None,
            active="all",
            scan_status="never_scanned",
            has_products=None,
            limit=100,
            offset=0,
            db=self.db,
        )

        self.assertEqual(completed["count"], 1)
        self.assertEqual(completed["items"][0]["last_product_count"], 12)
        self.assertEqual(never_scanned["count"], 1)
        self.assertEqual(
            never_scanned["items"][0]["last_scan_status"],
            "never_scanned",
        )

    def test_collection_payload_keeps_scan_link_for_existing_scanner_flow(self):
        import_collection_records(self.db, [record()])
        collection = self.db.query(MerchantCollection).one()
        run = start_scan_run(
            self.db,
            scan_run_id="scan_linked",
            source_url=collection.collection_url,
            merchant_name=collection.merchant.display_name,
            target_city_slug="london",
            normalized_category=collection.canonical_category,
            requested_image_mode="smart",
            requested_limit=25,
            collection_id=collection.id,
        )

        item = collection_payload(collection, latest_run=run)

        self.assertEqual(run.collection_id, collection.id)
        self.assertEqual(item["last_scan_status"], "running")
        self.assertEqual(item["last_scan_run_id"], "scan_linked")


if __name__ == "__main__":
    unittest.main()

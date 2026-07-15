import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.candidate_queue import (
    CandidateTransitionError,
    apply_candidate_queue_filter,
    reject_candidate,
    resolve_candidate_queue_status,
    restore_candidate,
)
from app.curation.product_candidate_publisher import (
    publish_approved_product_candidates,
)
from app.database import Base
from app.models import Brand, City, Country, Product, ProductCandidate


class CandidateQueueTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        country = Country(code="GB", name="United Kingdom")
        city = City(
            slug="london",
            name="London",
            country=country,
            latitude=51.5074,
            longitude=-0.1278,
        )
        brand = Brand(name="Example", country=country)
        self.db.add_all([country, city, brand])
        self.db.flush()
        self.city = city
        self.brand = brand

    def tearDown(self):
        self.db.close()

    def _candidate(
        self,
        external_id: str,
        *,
        review_status: str,
        product_is_active: bool | None = None,
    ) -> ProductCandidate:
        product = None
        if product_is_active is not None:
            product = Product(
                external_id=external_id,
                source="shopify",
                name=f"Product {external_id}",
                currency="USD",
                affiliate_url=f"https://shop.example.com/products/{external_id}",
                merchant_url=f"https://shop.example.com/products/{external_id}",
                product_image_url=f"https://cdn.example.com/{external_id}.jpg",
                brand_id=self.brand.id,
                city_id=self.city.id,
                is_active=product_is_active,
                availability_status="in_stock" if product_is_active else "archived",
            )
            self.db.add(product)
            self.db.flush()

        candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            brand_name="Example",
            external_product_id=external_id,
            title=f"Product {external_id}",
            price_amount=79,
            currency="USD",
            merchant_url=f"https://shop.example.com/products/{external_id}",
            image_url=f"https://cdn.example.com/{external_id}.jpg",
            availability="in_stock",
            normalized_category="dress",
            target_city_slug="london",
            haroona_score=90,
            score_reasons=[],
            review_status=review_status,
            promoted_product_id=product.id if product else None,
        )
        self.db.add(candidate)
        self.db.commit()
        return candidate

    def _queue_ids(self, status: str) -> set[int]:
        query = apply_candidate_queue_filter(
            self.db.query(ProductCandidate),
            status,
        )
        return {candidate.id for candidate in query.all()}

    def test_queue_filters_are_mutually_exclusive(self):
        approved = self._candidate("approved", review_status="approved")
        published = self._candidate(
            "published",
            review_status="approved",
            product_is_active=True,
        )
        approved_inactive = self._candidate(
            "approved-inactive",
            review_status="approved",
            product_is_active=False,
        )
        rejected_live = self._candidate(
            "rejected-live",
            review_status="rejected",
            product_is_active=True,
        )
        archived_live = self._candidate(
            "archived-live",
            review_status="archived",
            product_is_active=True,
        )

        self.assertEqual(
            self._queue_ids("approved"),
            {approved.id, approved_inactive.id},
        )
        self.assertEqual(
            self._queue_ids("published"),
            {published.id, rejected_live.id},
        )
        self.assertEqual(self._queue_ids("rejected"), set())
        self.assertEqual(self._queue_ids("archived"), {archived_live.id})

    def test_display_status_prioritizes_archive_then_live_product(self):
        self.assertEqual(resolve_candidate_queue_status("archived", True), "archived")
        self.assertEqual(resolve_candidate_queue_status("rejected", True), "published")
        self.assertEqual(resolve_candidate_queue_status("approved", False), "approved")

    def test_bulk_publish_reactivates_an_approved_linked_product(self):
        candidate = self._candidate(
            "reactivate",
            review_status="approved",
            product_is_active=False,
        )

        result = publish_approved_product_candidates(self.db, target_city_slug="london")

        self.db.refresh(candidate)
        product = self.db.query(Product).filter(Product.id == candidate.promoted_product_id).one()
        self.assertEqual(result["published"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertTrue(product.is_active)

    def test_restore_to_pending_deactivates_a_stale_live_product(self):
        candidate = self._candidate(
            "restore-review",
            review_status="archived",
            product_is_active=True,
        )

        result = restore_candidate(
            self.db,
            candidate,
            restored_by="test-curator",
            restore_to="pending",
        )

        self.db.refresh(candidate)
        product = self.db.query(Product).filter(Product.id == candidate.promoted_product_id).one()
        self.assertEqual(result["review_status"], "pending")
        self.assertFalse(product.is_active)
        self.assertEqual(self._queue_ids("pending"), {candidate.id})

    def test_live_candidate_cannot_be_rejected_directly(self):
        candidate = self._candidate(
            "live-review",
            review_status="pending",
            product_is_active=True,
        )

        with self.assertRaises(CandidateTransitionError) as raised:
            reject_candidate(
                self.db,
                candidate,
                reviewed_by="test-curator",
                reason="Not a fit",
            )

        self.assertIn("unpublished", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()

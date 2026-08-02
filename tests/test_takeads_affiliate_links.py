import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.affiliate_links import (
    AFFILIATE_FAILED,
    AFFILIATE_GENERATING,
    AFFILIATE_INVALID,
    AFFILIATE_NO_ELIGIBLE_OFFER,
    AFFILIATE_NOT_GENERATED,
    AFFILIATE_READY_TO_VERIFY,
    AFFILIATE_VERIFIED,
    PUBLISH_DESTINATION_RETAILER,
    _finalize_generation,
    affiliate_link_payload,
    invalidate_candidate_affiliate_link,
    resolve_takeads_affiliate_link,
    set_candidate_publish_destination,
    verify_candidate_affiliate_link,
)
from app.curation.product_candidate_publisher import publish_product_candidate
from app.curation.shopify_collection import CandidatePayload, upsert_product_candidates
from app.curation.takeads_client import (
    TAKEADS_REQUEST_TIMEOUT,
    TAKEADS_RESOLVE_URL,
    TakeadsResolveResult,
)
from app.database import Base
from app.models import City, Country, Product, ProductCandidate


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"data": []}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class TakeadsAffiliateLinkTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        country = Country(code="GB", name="United Kingdom")
        city = City(
            slug="london",
            name="London",
            country=country,
            latitude=Decimal("51.5074"),
            longitude=Decimal("-0.1278"),
        )
        self.db.add_all([country, city])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _candidate(
        self,
        external_id="takeads-1",
        *,
        review_status="approved",
        merchant_url=None,
    ):
        candidate = ProductCandidate(
            source="shopify",
            source_type="collection",
            source_url="https://shop.example.com/collections/new",
            merchant_name="Example",
            brand_name="Example",
            merchant_verification="verified",
            external_product_id=external_id,
            title=f"Product {external_id}",
            description="A city-ready cotton dress.",
            price_amount=Decimal("79.00"),
            currency="USD",
            merchant_url=merchant_url
            or f"https://shop.example.com/products/{external_id}?color=blue",
            image_url=f"https://cdn.example.com/{external_id}.jpg",
            availability="in_stock",
            normalized_category="dress",
            target_city_slug="london",
            eligibility_status="eligible",
            eligibility_reasons=[],
            platform_alignment_score=Decimal("8.0"),
            platform_alignment_reasons=["Recognized brand"],
            city_fit_score=90,
            city_fit_scores={"london": 90},
            scoring_confidence=85,
            scoring_method="deterministic_rules",
            scoring_version="hybrid_v1",
            haroona_score=90,
            score_reasons=[],
            review_status=review_status,
        )
        self.db.add(candidate)
        self.db.commit()
        return candidate

    def _success(self, candidate, tracking_link="https://tatrck.com/h/test-link"):
        return FakeResponse(
            body={
                "data": [
                    {
                        "iri": candidate.merchant_url,
                        "trackingLink": tracking_link,
                        "imageUrl": None,
                    }
                ]
            }
        )

    def _payload(self, candidate, merchant_url=None):
        return CandidatePayload(
            source=candidate.source,
            source_type=candidate.source_type,
            source_url=candidate.source_url,
            scan_run_id="scan-refresh",
            merchant_name=candidate.merchant_name,
            brand_name=candidate.brand_name,
            external_product_id=candidate.external_product_id,
            title=candidate.title,
            description=candidate.description,
            price_amount=candidate.price_amount,
            currency=candidate.currency,
            affiliate_url=None,
            merchant_url=merchant_url or candidate.merchant_url,
            image_url=candidate.image_url,
            availability=candidate.availability,
            normalized_category=candidate.normalized_category,
            target_city_slug=candidate.target_city_slug,
            city_connection_type=candidate.city_connection_type,
            city_connection_note=candidate.city_connection_note,
            merchant_verification=candidate.merchant_verification,
            merchant_profile_key=candidate.merchant_profile_key,
            eligibility_status=candidate.eligibility_status,
            eligibility_reasons=candidate.eligibility_reasons,
            platform_alignment_score=candidate.platform_alignment_score,
            platform_alignment_reasons=candidate.platform_alignment_reasons,
            city_fit_score=candidate.city_fit_score,
            city_fit_scores=candidate.city_fit_scores,
            secondary_city_slug=candidate.secondary_city_slug,
            scoring_confidence=candidate.scoring_confidence,
            scoring_method=candidate.scoring_method,
            scoring_version=candidate.scoring_version,
            haroona_score=candidate.haroona_score,
            score_reasons=candidate.score_reasons,
            review_notes=candidate.review_notes,
        )

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_exact_product_url_stable_subid_and_response_mapping(self, mock_put):
        candidate = self._candidate()
        original_url = candidate.merchant_url
        mock_put.return_value = self._success(candidate)

        first = resolve_takeads_affiliate_link(self.db, candidate)
        second = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(first["status"], AFFILIATE_READY_TO_VERIFY)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(candidate.merchant_url, original_url)
        self.assertEqual(candidate.affiliate_sub_id, f"haroona_product_{candidate.id}")
        self.assertEqual(candidate.affiliate_provider, "takeads")
        self.assertEqual(candidate.affiliate_provider_reference, original_url)
        self.assertEqual(candidate.affiliate_link_attempt_count, 1)
        self.assertIsNone(candidate.affiliate_link_verified_at)
        self.assertIsNone(candidate.affiliate_link_verified_by)
        mock_put.assert_called_once_with(
            TAKEADS_RESOLVE_URL,
            headers={
                "Authorization": "Bearer test-public-key",
                "Content-Type": "application/json",
            },
            json={
                "iris": [original_url],
                "subId": f"haroona_product_{candidate.id}",
            },
            timeout=TAKEADS_REQUEST_TIMEOUT,
        )

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_empty_data_is_no_eligible_offer_not_malformed_json(self, mock_put):
        candidate = self._candidate("no-offer")
        mock_put.return_value = FakeResponse(body={"data": []})

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_NO_ELIGIBLE_OFFER)
        self.assertEqual(result["error_code"], "takeads_no_eligible_offer")
        self.assertIn("did not find an eligible", result["error_message"])
        self.assertIsNone(candidate.affiliate_url)

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_malformed_and_mismatched_responses_are_sanitized(self, mock_put):
        cases = [
            (
                FakeResponse(body={}),
                "takeads_invalid_response",
            ),
            (
                FakeResponse(body={"data": "wrong"}),
                "takeads_invalid_response",
            ),
            (
                FakeResponse(
                    body={
                        "data": [
                            {
                                "iri": "https://other.example.com/products/wrong",
                                "trackingLink": "https://tatrck.com/h/wrong",
                            }
                        ]
                    }
                ),
                "takeads_iri_mismatch",
            ),
            (
                FakeResponse(body=ValueError("not json")),
                "takeads_invalid_response",
            ),
        ]

        for index, (response, code) in enumerate(cases):
            with self.subTest(code=code, index=index):
                candidate = self._candidate(f"malformed-{index}")
                mock_put.return_value = response
                result = resolve_takeads_affiliate_link(self.db, candidate)
                self.assertEqual(result["status"], AFFILIATE_FAILED)
                self.assertEqual(result["error_code"], code)
                self.assertNotIn("test-public-key", result["error_message"])

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_timeout_is_retryable_and_attempt_count_is_accurate(self, mock_put):
        candidate = self._candidate("retry")
        mock_put.side_effect = [requests.Timeout(), self._success(candidate)]

        failed = resolve_takeads_affiliate_link(self.db, candidate)
        stable_sub_id = candidate.affiliate_sub_id
        recovered = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(failed["status"], AFFILIATE_FAILED)
        self.assertEqual(failed["error_code"], "takeads_timeout")
        self.assertEqual(recovered["status"], AFFILIATE_READY_TO_VERIFY)
        self.assertEqual(candidate.affiliate_sub_id, stable_sub_id)
        self.assertEqual(candidate.affiliate_link_attempt_count, 2)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_is_sanitized_and_never_returned(self):
        candidate = self._candidate("missing-key")

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_FAILED)
        self.assertEqual(result["error_code"], "takeads_not_configured")
        self.assertNotIn("TAKEADS_PUBLIC_KEY", result["error_message"])
        self.assertNotIn("Authorization", affiliate_link_payload(candidate))

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_http_auth_rate_limit_and_provider_failures_are_sanitized(self, mock_put):
        expected = {
            401: "takeads_unauthorized",
            403: "takeads_forbidden",
            429: "takeads_rate_limited",
            500: "takeads_unavailable",
            503: "takeads_unavailable",
        }

        for status_code, error_code in expected.items():
            with self.subTest(status_code=status_code):
                candidate = self._candidate(f"http-{status_code}")
                mock_put.return_value = FakeResponse(status_code=status_code)
                result = resolve_takeads_affiliate_link(self.db, candidate)
                self.assertEqual(result["status"], AFFILIATE_FAILED)
                self.assertEqual(result["error_code"], error_code)
                self.assertNotIn("test-public-key", result["error_message"])

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_duplicate_generation_returns_current_in_progress_state(self, mock_put):
        candidate = self._candidate("concurrent")
        candidate.affiliate_provider = "takeads"
        candidate.affiliate_sub_id = f"haroona_product_{candidate.id}"
        candidate.affiliate_link_status = AFFILIATE_GENERATING
        candidate.affiliate_link_attempt_count = 1
        candidate.affiliate_link_last_attempted_at = datetime.now(timezone.utc)
        self.db.commit()

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_GENERATING)
        self.assertTrue(result["reused"])
        self.assertTrue(result["in_progress"])
        self.assertEqual(candidate.affiliate_link_attempt_count, 1)
        mock_put.assert_not_called()

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_stale_generating_state_can_recover(self, mock_put):
        candidate = self._candidate("stale")
        candidate.affiliate_provider = "takeads"
        candidate.affiliate_sub_id = f"haroona_product_{candidate.id}"
        candidate.affiliate_link_status = AFFILIATE_GENERATING
        candidate.affiliate_link_attempt_count = 1
        candidate.affiliate_link_last_attempted_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        self.db.commit()
        mock_put.return_value = self._success(candidate)

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_READY_TO_VERIFY)
        self.assertEqual(candidate.affiliate_link_attempt_count, 2)
        mock_put.assert_called_once()

    def test_delayed_response_cannot_overwrite_a_newer_success(self):
        candidate = self._candidate("delayed-response")
        candidate.affiliate_provider = "takeads"
        candidate.affiliate_sub_id = f"haroona_product_{candidate.id}"
        candidate.affiliate_link_status = AFFILIATE_GENERATING
        candidate.affiliate_link_attempt_count = 1
        candidate.affiliate_link_last_attempted_at = datetime.now(timezone.utc)
        self.db.commit()

        # Keep attempt one loaded in this session while another request commits
        # a newer successful attempt.
        self.assertEqual(candidate.affiliate_link_attempt_count, 1)
        other_db = sessionmaker(bind=self.db.get_bind())()
        try:
            current = other_db.get(ProductCandidate, candidate.id)
            current.affiliate_link_status = AFFILIATE_READY_TO_VERIFY
            current.affiliate_link_attempt_count = 2
            current.affiliate_url = "https://tatrck.com/h/newer-success"
            current.affiliate_link_generated_at = datetime.now(timezone.utc)
            other_db.commit()
        finally:
            other_db.close()

        result = _finalize_generation(
            self.db,
            candidate_id=candidate.id,
            attempt_number=1,
            result=TakeadsResolveResult(
                tracking_link="https://tatrck.com/h/stale-success",
                returned_iri=candidate.merchant_url,
            ),
        )

        self.assertTrue(result["stale_result_ignored"])
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(
            result["affiliate_url"],
            "https://tatrck.com/h/newer-success",
        )

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_approval_is_idempotent_and_starts_generation(self, mock_put):
        from app.routers.catalog_admin import (
            ReviewCandidateRequest,
            approve_product_candidate,
        )

        candidate = self._candidate("approval", review_status="pending")
        mock_put.return_value = self._success(candidate)
        admin = SimpleNamespace(id="curator-1", email="curator@example.com")

        first = approve_product_candidate(
            candidate.id,
            ReviewCandidateRequest(reviewed_by="spoofed"),
            self.db,
            admin,
        )
        second = approve_product_candidate(
            candidate.id,
            ReviewCandidateRequest(reviewed_by="spoofed-again"),
            self.db,
            admin,
        )

        self.assertEqual(candidate.review_status, "approved")
        self.assertEqual(candidate.reviewed_by, "curator@example.com")
        self.assertEqual(first["affiliate"]["status"], AFFILIATE_READY_TO_VERIFY)
        self.assertTrue(second["affiliate"]["reused"])
        mock_put.assert_called_once()

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_verification_uses_authenticated_curator_and_cannot_be_spoofed(self, mock_put):
        from app.routers.catalog_admin import verify_product_candidate_affiliate_link

        candidate = self._candidate("verify")
        mock_put.return_value = self._success(candidate)
        resolve_takeads_affiliate_link(self.db, candidate)
        admin = SimpleNamespace(id="curator-2", email="real-curator@example.com")

        result = verify_product_candidate_affiliate_link(
            candidate.id,
            self.db,
            admin,
        )

        self.assertEqual(result["affiliate"]["status"], AFFILIATE_VERIFIED)
        self.assertEqual(
            candidate.affiliate_link_verified_by,
            "real-curator@example.com",
        )
        self.assertIsNotNone(candidate.affiliate_link_verified_at)

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_invalidation_preserves_url_and_publishes_retailer_fallback(self, mock_put):
        candidate = self._candidate("invalid")
        mock_put.return_value = self._success(candidate)
        resolve_takeads_affiliate_link(self.db, candidate)
        generated_url = candidate.affiliate_url
        verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified_by="curator@example.com",
        )

        invalidated = invalidate_candidate_affiliate_link(
            self.db,
            candidate,
            invalidated_by="curator@example.com",
            reason="Redirected to a category page",
        )

        self.assertEqual(invalidated["status"], AFFILIATE_INVALID)
        self.assertEqual(candidate.affiliate_url, generated_url)
        self.assertIsNone(candidate.affiliate_link_verified_at)
        self.assertEqual(
            candidate.affiliate_link_invalidated_by,
            "curator@example.com",
        )
        published = publish_product_candidate(self.db, candidate)
        product = self.db.get(Product, published["product_id"])
        self.assertFalse(product.is_affiliate)
        self.assertIsNone(product.affiliate_url)
        self.assertEqual(product.merchant_url, candidate.merchant_url)
        self.assertTrue(published["using_retailer_fallback"])

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_regeneration_replaces_link_and_clears_verification(self, mock_put):
        candidate = self._candidate("regenerate")
        mock_put.side_effect = [
            self._success(candidate, "https://tatrck.com/h/first"),
            self._success(candidate, "https://tatrck.com/h/second"),
        ]
        resolve_takeads_affiliate_link(self.db, candidate)
        verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified_by="curator@example.com",
        )

        regenerated = resolve_takeads_affiliate_link(
            self.db,
            candidate,
            force=True,
        )

        self.assertEqual(regenerated["status"], AFFILIATE_READY_TO_VERIFY)
        self.assertEqual(candidate.affiliate_url, "https://tatrck.com/h/second")
        self.assertEqual(candidate.affiliate_link_attempt_count, 2)
        self.assertIsNone(candidate.affiliate_link_verified_at)
        self.assertIsNone(candidate.affiliate_link_verified_by)

    def test_direct_publish_uses_retailer_fallback_until_verification(self):
        from app.routers.catalog_admin import PublishCandidateRequest, publish_candidate

        candidate = self._candidate("publish-conflict")
        candidate.affiliate_url = "https://tatrck.com/h/unverified"
        candidate.affiliate_link_status = AFFILIATE_READY_TO_VERIFY
        self.db.commit()
        admin = SimpleNamespace(id="curator-3", email="curator@example.com")

        result = publish_candidate(
            candidate.id,
            PublishCandidateRequest(published_by="spoofed"),
            self.db,
            admin,
        )
        product = self.db.get(Product, result["product_id"])

        self.assertFalse(product.is_affiliate)
        self.assertIsNone(product.affiliate_url)
        self.assertEqual(product.merchant_url, candidate.merchant_url)
        self.assertTrue(result["using_retailer_fallback"])

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_verified_product_publishes_with_only_verified_handoff_url(self, mock_put):
        candidate = self._candidate("complete-flow")
        mock_put.return_value = self._success(
            candidate,
            "https://tatrck.com/h/complete-flow",
        )
        resolve_takeads_affiliate_link(self.db, candidate)
        verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified_by="curator@example.com",
        )

        published = publish_product_candidate(
            self.db,
            candidate,
            published_by="curator@example.com",
        )
        product = (
            self.db.query(Product)
            .filter(Product.id == published["product_id"])
            .one()
        )

        self.assertTrue(product.is_active)
        self.assertTrue(product.is_affiliate)
        self.assertEqual(product.merchant_url, candidate.merchant_url)
        self.assertEqual(
            product.affiliate_url,
            "https://tatrck.com/h/complete-flow",
        )

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_active_product_falls_back_while_affiliate_link_regenerates(self, mock_put):
        candidate = self._candidate("legacy-active")
        product = Product(
            external_id="legacy-active",
            source="shopify",
            name="Legacy active product",
            currency="USD",
            affiliate_url="https://tatrck.com/h/legacy",
            merchant_url=candidate.merchant_url,
            is_affiliate=True,
            product_image_url=candidate.image_url,
            brand_id=1,
            city_id=1,
            is_active=True,
        )
        self.db.add(product)
        self.db.flush()
        candidate.promoted_product_id = product.id
        candidate.affiliate_url = product.affiliate_url
        candidate.affiliate_link_status = AFFILIATE_VERIFIED
        candidate.affiliate_link_verified_at = datetime.now(timezone.utc)
        self.db.commit()
        mock_put.return_value = self._success(
            candidate,
            "https://tatrck.com/h/regenerated-live",
        )

        result = resolve_takeads_affiliate_link(self.db, candidate, force=True)

        self.assertTrue(product.is_active)
        self.assertFalse(product.is_affiliate)
        self.assertIsNone(product.affiliate_url)
        self.assertEqual(product.merchant_url, candidate.merchant_url)
        self.assertEqual(result["status"], AFFILIATE_READY_TO_VERIFY)
        mock_put.assert_called_once()

    @patch.dict(os.environ, {"TAKEADS_PUBLIC_KEY": "test-public-key"})
    @patch("app.curation.takeads_client.requests.put")
    def test_live_retailer_fallback_upgrades_and_downgrades_with_verification(
        self,
        mock_put,
    ):
        candidate = self._candidate("live-fallback")
        mock_put.return_value = self._success(
            candidate,
            "https://tatrck.com/h/live-fallback",
        )
        resolve_takeads_affiliate_link(self.db, candidate)
        published = publish_product_candidate(self.db, candidate)
        product = self.db.get(Product, published["product_id"])
        self.assertFalse(product.is_affiliate)

        verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified_by="curator@example.com",
        )
        self.db.refresh(product)
        self.assertTrue(product.is_affiliate)
        self.assertEqual(
            product.affiliate_url,
            "https://tatrck.com/h/live-fallback",
        )

        invalidate_candidate_affiliate_link(
            self.db,
            candidate,
            invalidated_by="curator@example.com",
            reason="Redirected to the retailer homepage",
        )
        self.db.refresh(product)
        self.assertFalse(product.is_affiliate)
        self.assertIsNone(product.affiliate_url)
        self.assertEqual(product.merchant_url, candidate.merchant_url)

    def test_direct_retailer_preference_persists_and_updates_live_product(self):
        candidate = self._candidate("retailer-preference")
        candidate.affiliate_link_status = AFFILIATE_VERIFIED
        candidate.affiliate_url = "https://tatrck.com/h/retailer-preference"
        candidate.affiliate_link_verified_at = datetime.now(timezone.utc)
        self.db.commit()
        published = publish_product_candidate(self.db, candidate)
        product = self.db.get(Product, published["product_id"])
        self.assertTrue(product.is_affiliate)

        result = set_candidate_publish_destination(
            self.db,
            candidate,
            destination=PUBLISH_DESTINATION_RETAILER,
        )
        self.db.refresh(candidate)
        self.db.refresh(product)

        self.assertEqual(candidate.publish_destination, "retailer")
        self.assertEqual(result["resolved_publish_destination"], "retailer")
        self.assertTrue(result["active_product_updated"])
        self.assertFalse(product.is_affiliate)
        self.assertIsNone(product.affiliate_url)

    def test_rescan_preserves_state_for_same_url_and_resets_changed_url(self):
        candidate = self._candidate("rescan")
        candidate.affiliate_url = "https://tatrck.com/h/rescan"
        candidate.affiliate_provider = "takeads"
        candidate.affiliate_link_status = AFFILIATE_VERIFIED
        candidate.affiliate_sub_id = f"haroona_product_{candidate.id}"
        candidate.affiliate_link_attempt_count = 2
        candidate.affiliate_link_verified_at = datetime.now(timezone.utc)
        self.db.commit()

        upsert_product_candidates(self.db, [self._payload(candidate)])
        self.db.refresh(candidate)
        self.assertEqual(candidate.affiliate_link_status, AFFILIATE_VERIFIED)
        self.assertEqual(candidate.affiliate_url, "https://tatrck.com/h/rescan")

        stable_sub_id = candidate.affiliate_sub_id
        changed_url = "https://shop.example.com/products/rescan-new?size=m"
        upsert_product_candidates(
            self.db,
            [self._payload(candidate, merchant_url=changed_url)],
        )
        self.db.refresh(candidate)
        self.assertEqual(candidate.merchant_url, changed_url)
        self.assertEqual(candidate.affiliate_link_status, AFFILIATE_NOT_GENERATED)
        self.assertIsNone(candidate.affiliate_url)
        self.assertEqual(candidate.affiliate_sub_id, stable_sub_id)
        self.assertEqual(candidate.affiliate_link_attempt_count, 2)


if __name__ == "__main__":
    unittest.main()

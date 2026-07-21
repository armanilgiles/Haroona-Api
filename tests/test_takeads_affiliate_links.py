import os
import unittest
from decimal import Decimal
from unittest.mock import patch

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.curation.affiliate_links import (
    AFFILIATE_FAILED,
    AFFILIATE_GENERATED,
    AFFILIATE_NOT_REQUESTED,
    AFFILIATE_VERIFIED,
    TAKEADS_REQUEST_TIMEOUT_SECONDS,
    TAKEADS_RESOLVE_URL,
    resolve_takeads_affiliate_link,
    verify_candidate_affiliate_link,
)
from app.curation.candidate_queue import approve_candidate
from app.curation.product_candidate_publisher import publish_product_candidate
from app.curation.shopify_collection import CandidatePayload, upsert_product_candidates
from app.database import Base
from app.models import City, Country, Product, ProductCandidate


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"data": []}

    def json(self):
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

    def _success(self, candidate, tracking_link="https://go.takeads.com/click/abc"):
        return FakeResponse(
            body={
                "data": [
                    {
                        "iri": candidate.merchant_url,
                        "trackingLink": tracking_link,
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

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_exact_url_payload_and_stable_sub_id_are_reused(self, mock_put):
        candidate = self._candidate()
        mock_put.return_value = self._success(candidate)

        first = resolve_takeads_affiliate_link(self.db, candidate)
        second = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(first["status"], AFFILIATE_GENERATED)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(candidate.affiliate_sub_id, f"haroona-product-{candidate.id}")
        self.assertEqual(candidate.affiliate_url, "https://go.takeads.com/click/abc")
        mock_put.assert_called_once_with(
            TAKEADS_RESOLVE_URL,
            headers={
                "Authorization": "Bearer platform-secret",
                "Content-Type": "application/json",
            },
            json={
                "iris": [candidate.merchant_url],
                "subId": f"haroona-product-{candidate.id}",
                "withImages": False,
            },
            timeout=TAKEADS_REQUEST_TIMEOUT_SECONDS,
        )

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_retry_after_timeout_reuses_the_same_sub_id(self, mock_put):
        candidate = self._candidate("retry")
        mock_put.side_effect = [requests.Timeout(), self._success(candidate)]

        failed = resolve_takeads_affiliate_link(self.db, candidate)
        stable_sub_id = candidate.affiliate_sub_id
        generated = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(failed["status"], AFFILIATE_FAILED)
        self.assertIn("did not respond", failed["error_message"])
        self.assertEqual(generated["status"], AFFILIATE_GENERATED)
        self.assertEqual(candidate.affiliate_sub_id, stable_sub_id)
        self.assertEqual(mock_put.call_args_list[0].kwargs["json"]["subId"], stable_sub_id)
        self.assertEqual(mock_put.call_args_list[1].kwargs["json"]["subId"], stable_sub_id)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_backend_key_returns_an_understandable_failure(self):
        candidate = self._candidate("missing-key")

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_FAILED)
        self.assertEqual(result["error_code"], "takeads_not_configured")
        self.assertIn("TAKEADS_PLATFORM_API_KEY", result["error_message"])
        self.assertIsNone(candidate.affiliate_url)

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_empty_success_response_is_a_retryable_failure(self, mock_put):
        candidate = self._candidate("unsupported")
        mock_put.return_value = FakeResponse(status_code=200, body={"data": []})

        result = resolve_takeads_affiliate_link(self.db, candidate)

        self.assertEqual(result["status"], AFFILIATE_FAILED)
        self.assertEqual(result["error_code"], "takeads_unsupported_product")
        self.assertIn("may not be supported", result["error_message"])

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_takeads_http_failures_are_sanitized_for_curators(self, mock_put):
        expected = {
            400: "invalid_product_url",
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
                self.assertNotIn("platform-secret", result["error_message"])

    @patch.dict(
        os.environ,
        {
            "TAKEADS_PLATFORM_API_KEY": "platform-secret",
            "SECRET_KEY": "test-secret",
        },
    )
    @patch("app.curation.affiliate_links.requests.put")
    def test_approve_endpoint_stays_approved_when_takeads_fails(self, mock_put):
        from app.routers.catalog_admin import (
            ReviewCandidateRequest,
            approve_product_candidate,
        )

        candidate = self._candidate("approve-failure", review_status="pending")
        mock_put.return_value = FakeResponse(status_code=503)

        result = approve_product_candidate(
            candidate.id,
            ReviewCandidateRequest(reviewed_by="test-curator"),
            self.db,
            object(),
        )

        self.db.refresh(candidate)
        self.assertEqual(candidate.review_status, "approved")
        self.assertEqual(candidate.affiliate_link_status, AFFILIATE_FAILED)
        self.assertEqual(result["affiliate"]["status"], AFFILIATE_FAILED)
        self.assertIn("temporarily unavailable", result["affiliate"]["error_message"])

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_manual_verification_and_wrong_product_transitions(self, mock_put):
        candidate = self._candidate("verify")
        mock_put.return_value = self._success(candidate)
        resolve_takeads_affiliate_link(self.db, candidate)

        verified = verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified=True,
            verified_by="test-curator",
        )
        self.assertEqual(verified["status"], AFFILIATE_VERIFIED)
        self.assertEqual(candidate.affiliate_link_verified_by, "test-curator")

        failed = verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified=False,
            verified_by="test-curator",
        )
        self.assertEqual(failed["status"], AFFILIATE_FAILED)
        self.assertEqual(failed["error_code"], "manual_verification_failed")
        self.assertIsNone(candidate.affiliate_url)

    @patch.dict(os.environ, {"TAKEADS_PLATFORM_API_KEY": "platform-secret"})
    @patch("app.curation.affiliate_links.requests.put")
    def test_complete_approve_generate_verify_publish_workflow(self, mock_put):
        candidate = self._candidate("complete-flow", review_status="pending")
        mock_put.return_value = self._success(
            candidate,
            tracking_link="https://go.takeads.com/click/complete-flow",
        )

        approve_candidate(self.db, candidate, reviewed_by="test-curator")
        generated = resolve_takeads_affiliate_link(self.db, candidate)
        verified = verify_candidate_affiliate_link(
            self.db,
            candidate,
            verified=True,
            verified_by="test-curator",
        )
        published = publish_product_candidate(
            self.db,
            candidate,
            published_by="test-curator",
        )

        product = self.db.query(Product).filter(Product.id == published["product_id"]).one()
        self.assertEqual(generated["status"], AFFILIATE_GENERATED)
        self.assertEqual(verified["status"], AFFILIATE_VERIFIED)
        self.assertTrue(product.is_active)
        self.assertTrue(product.is_affiliate)
        self.assertEqual(product.merchant_url, candidate.merchant_url)
        self.assertEqual(
            product.affiliate_url,
            "https://go.takeads.com/click/complete-flow",
        )

    def test_rescan_preserves_link_for_same_url_and_invalidates_changed_url(self):
        candidate = self._candidate("rescan")
        candidate.affiliate_url = "https://go.takeads.com/click/rescan"
        candidate.affiliate_link_status = AFFILIATE_VERIFIED
        candidate.affiliate_sub_id = f"haroona-product-{candidate.id}"
        self.db.commit()

        upsert_product_candidates(self.db, [self._payload(candidate)])
        self.db.refresh(candidate)
        self.assertEqual(candidate.affiliate_link_status, AFFILIATE_VERIFIED)
        self.assertEqual(candidate.affiliate_url, "https://go.takeads.com/click/rescan")

        stable_sub_id = candidate.affiliate_sub_id
        changed_url = "https://shop.example.com/products/rescan-new?size=m"
        upsert_product_candidates(
            self.db,
            [self._payload(candidate, merchant_url=changed_url)],
        )
        self.db.refresh(candidate)
        self.assertEqual(candidate.merchant_url, changed_url)
        self.assertEqual(candidate.affiliate_link_status, AFFILIATE_NOT_REQUESTED)
        self.assertIsNone(candidate.affiliate_url)
        self.assertEqual(candidate.affiliate_sub_id, stable_sub_id)


if __name__ == "__main__":
    unittest.main()

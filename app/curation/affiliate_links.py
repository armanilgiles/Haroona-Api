from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.curation.takeads_client import (
    TakeadsClient,
    TakeadsClientError,
    TakeadsResolveResult,
)
from app.models import Product, ProductCandidate


logger = logging.getLogger(__name__)

AFFILIATE_NOT_GENERATED = "not_generated"
AFFILIATE_GENERATING = "generating"
AFFILIATE_READY_TO_VERIFY = "ready_to_verify"
AFFILIATE_VERIFIED = "verified"
AFFILIATE_NO_ELIGIBLE_OFFER = "no_eligible_offer"
AFFILIATE_FAILED = "failed"
AFFILIATE_INVALID = "invalid"

# Compatibility aliases for older internal imports. The canonical persisted
# values are the constants above.
AFFILIATE_NOT_REQUESTED = AFFILIATE_NOT_GENERATED
AFFILIATE_GENERATED = AFFILIATE_READY_TO_VERIFY

AFFILIATE_LINK_STATUSES = {
    AFFILIATE_NOT_GENERATED,
    AFFILIATE_GENERATING,
    AFFILIATE_READY_TO_VERIFY,
    AFFILIATE_VERIFIED,
    AFFILIATE_NO_ELIGIBLE_OFFER,
    AFFILIATE_FAILED,
    AFFILIATE_INVALID,
}
LEGACY_AFFILIATE_LINK_STATUSES = {"not_requested", "generated"}

TAKEADS_PROVIDER = "takeads"
AFFILIATE_GENERATION_STALE_AFTER = timedelta(minutes=2)
_SUB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class AffiliateLinkTransitionError(ValueError):
    pass


class AffiliateLinkPersistenceError(RuntimeError):
    pass


class AffiliateLinkPublicationError(ValueError):
    code = "AFFILIATE_LINK_NOT_VERIFIED"
    message = (
        "The affiliate link must be generated and verified before this product "
        "can be published."
    )

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _valid_http_url(value: str | None) -> bool:
    cleaned = _clean(value)
    if not cleaned:
        return False
    parsed = urlsplit(cleaned)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _canonical_status(value: str | None) -> str:
    normalized = _clean(value) or AFFILIATE_NOT_GENERATED
    if normalized == "not_requested":
        return AFFILIATE_NOT_GENERATED
    if normalized == "generated":
        return AFFILIATE_READY_TO_VERIFY
    return normalized


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _affiliate_sub_id(candidate: ProductCandidate) -> str:
    current = _clean(candidate.affiliate_sub_id)
    if current:
        if not _SUB_ID_PATTERN.fullmatch(current):
            raise AffiliateLinkTransitionError(
                "The saved affiliate SubID contains unsupported characters"
            )
        return current
    if not candidate.id:
        raise AffiliateLinkTransitionError(
            "Candidate must be saved before an affiliate link can be generated"
        )
    candidate.affiliate_sub_id = f"haroona_product_{candidate.id}"
    return candidate.affiliate_sub_id


def affiliate_link_payload(candidate: ProductCandidate) -> dict[str, Any]:
    return {
        "provider": candidate.affiliate_provider,
        "provider_reference": candidate.affiliate_provider_reference,
        "status": _canonical_status(candidate.affiliate_link_status),
        "affiliate_url": candidate.affiliate_url,
        "original_product_url": candidate.merchant_url,
        "merchant_url": candidate.merchant_url,
        "sub_id": candidate.affiliate_sub_id,
        "attempt_count": candidate.affiliate_link_attempt_count or 0,
        "error_code": candidate.affiliate_link_error_code,
        "error_message": candidate.affiliate_link_error_message,
        "last_attempted_at": candidate.affiliate_link_last_attempted_at,
        "generated_at": candidate.affiliate_link_generated_at,
        "verified_at": candidate.affiliate_link_verified_at,
        "verified_by": candidate.affiliate_link_verified_by,
        "invalidated_at": candidate.affiliate_link_invalidated_at,
        "invalidated_by": candidate.affiliate_link_invalidated_by,
    }


def affiliate_link_is_publishable(candidate: ProductCandidate) -> bool:
    return bool(
        _canonical_status(candidate.affiliate_link_status) == AFFILIATE_VERIFIED
        and _valid_http_url(candidate.affiliate_url)
        and candidate.affiliate_link_verified_at is not None
    )


def affiliate_link_publish_block_reason(candidate: ProductCandidate) -> str | None:
    if affiliate_link_is_publishable(candidate):
        return None

    status = _canonical_status(candidate.affiliate_link_status)
    if status == AFFILIATE_GENERATING:
        return "Wait for affiliate-link generation to finish before publishing."
    if status == AFFILIATE_READY_TO_VERIFY:
        return "Open and verify the affiliate link before publishing."
    if status == AFFILIATE_NO_ELIGIBLE_OFFER:
        return "This product has no eligible Takeads offer."
    if status == AFFILIATE_FAILED:
        return "Retry affiliate-link generation before publishing."
    if status == AFFILIATE_INVALID:
        return (
            "The affiliate link was reported invalid. Regenerate and verify it "
            "before publishing."
        )
    if status == AFFILIATE_VERIFIED:
        return "Affiliate verification is incomplete. Verify the link again."
    return "Generate an affiliate link before publishing."


def require_publishable_affiliate_link(candidate: ProductCandidate) -> None:
    reason = affiliate_link_publish_block_reason(candidate)
    if reason:
        raise AffiliateLinkPublicationError(reason)


def resolve_candidate_workflow_status(
    candidate: ProductCandidate,
    product_is_active: bool | None,
) -> str:
    if product_is_active is True:
        return "published"

    review_status = (candidate.review_status or "pending").strip().lower()
    if review_status == "pending":
        return "discovered"
    if review_status != "approved":
        return review_status

    affiliate_status = _canonical_status(candidate.affiliate_link_status)
    return {
        AFFILIATE_GENERATING: "affiliate_link_generating",
        AFFILIATE_READY_TO_VERIFY: "affiliate_link_ready_to_verify",
        AFFILIATE_VERIFIED: "affiliate_link_verified",
        AFFILIATE_NO_ELIGIBLE_OFFER: "affiliate_link_no_eligible_offer",
        AFFILIATE_FAILED: "affiliate_link_failed",
        AFFILIATE_INVALID: "affiliate_link_invalid",
    }.get(affiliate_status, "approved")


def _locked_candidate(db: Session, candidate_id: int) -> ProductCandidate:
    candidate = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.id == candidate_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not candidate:
        raise AffiliateLinkTransitionError("Candidate not found")
    return candidate


def _candidate_has_active_product(
    db: Session,
    candidate: ProductCandidate,
) -> bool:
    if not candidate.promoted_product_id:
        return False
    return bool(
        db.query(Product.id)
        .filter(Product.id == candidate.promoted_product_id)
        .filter(Product.is_active.is_(True))
        .first()
    )


def _generation_is_current(candidate: ProductCandidate, now: datetime) -> bool:
    if _canonical_status(candidate.affiliate_link_status) != AFFILIATE_GENERATING:
        return False
    attempted_at = _as_utc(candidate.affiliate_link_last_attempted_at)
    return bool(
        attempted_at
        and now - attempted_at < AFFILIATE_GENERATION_STALE_AFTER
    )


def _commit_or_raise(db: Session, *, operation: str) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "affiliate_link_persistence_failed operation=%s",
            operation,
        )
        raise AffiliateLinkPersistenceError(
            "The affiliate-link state could not be saved. Retry the operation."
        ) from exc


def _start_generation(
    db: Session,
    candidate_id: int,
    *,
    force: bool,
) -> tuple[ProductCandidate, int] | dict[str, Any]:
    candidate = _locked_candidate(db, candidate_id)
    if candidate.review_status != "approved":
        raise AffiliateLinkTransitionError(
            "Approve the product before generating its affiliate link"
        )

    now = datetime.now(timezone.utc)
    status = _canonical_status(candidate.affiliate_link_status)
    if _generation_is_current(candidate, now):
        return {
            **affiliate_link_payload(candidate),
            "reused": True,
            "in_progress": True,
        }

    if (
        not force
        and status in {AFFILIATE_READY_TO_VERIFY, AFFILIATE_VERIFIED}
        and _valid_http_url(candidate.affiliate_url)
    ):
        return {
            **affiliate_link_payload(candidate),
            "reused": True,
            "in_progress": False,
        }

    if force and _candidate_has_active_product(db, candidate):
        raise AffiliateLinkTransitionError(
            "Unpublish the product before regenerating its affiliate link"
        )

    product_url = _clean(candidate.merchant_url)
    if not _valid_http_url(product_url):
        candidate.affiliate_link_status = AFFILIATE_FAILED
        candidate.affiliate_link_error_code = "invalid_product_url"
        candidate.affiliate_link_error_message = (
            "The original product URL is missing or invalid. Correct it before retrying."
        )
        candidate.affiliate_link_last_attempted_at = now
        candidate.affiliate_link_verified_at = None
        candidate.affiliate_link_verified_by = None
        _commit_or_raise(db, operation="record_invalid_product_url")
        return {
            **affiliate_link_payload(candidate),
            "reused": False,
            "in_progress": False,
        }

    _affiliate_sub_id(candidate)
    attempt_number = (candidate.affiliate_link_attempt_count or 0) + 1
    candidate.affiliate_provider = TAKEADS_PROVIDER
    candidate.affiliate_link_status = AFFILIATE_GENERATING
    candidate.affiliate_link_attempt_count = attempt_number
    candidate.affiliate_link_last_attempted_at = now
    candidate.affiliate_link_error_code = None
    candidate.affiliate_link_error_message = None
    candidate.affiliate_link_verified_at = None
    candidate.affiliate_link_verified_by = None
    _commit_or_raise(db, operation="start_generation")
    logger.info(
        "affiliate_link_generation_started product_id=%s provider=%s attempt=%s",
        candidate.id,
        TAKEADS_PROVIDER,
        attempt_number,
    )
    return candidate, attempt_number


def _finalize_generation(
    db: Session,
    *,
    candidate_id: int,
    attempt_number: int,
    result: TakeadsResolveResult | None = None,
    error: TakeadsClientError | None = None,
) -> dict[str, Any]:
    candidate = _locked_candidate(db, candidate_id)
    current_attempt = candidate.affiliate_link_attempt_count or 0
    current_status = _canonical_status(candidate.affiliate_link_status)
    if (
        current_attempt != attempt_number
        or current_status != AFFILIATE_GENERATING
    ):
        logger.warning(
            "affiliate_link_stale_result_ignored product_id=%s provider=%s attempt=%s current_attempt=%s current_status=%s",
            candidate.id,
            TAKEADS_PROVIDER,
            attempt_number,
            current_attempt,
            current_status,
        )
        return {
            **affiliate_link_payload(candidate),
            "reused": True,
            "in_progress": current_status == AFFILIATE_GENERATING,
            "stale_result_ignored": True,
        }

    now = datetime.now(timezone.utc)
    if error is not None:
        candidate.affiliate_link_status = AFFILIATE_FAILED
        candidate.affiliate_link_error_code = error.code
        candidate.affiliate_link_error_message = error.message
        _commit_or_raise(db, operation="record_provider_failure")
        logger.warning(
            "affiliate_link_generation_failed product_id=%s provider=%s attempt=%s http_status=%s code=%s",
            candidate.id,
            TAKEADS_PROVIDER,
            attempt_number,
            error.http_status,
            error.code,
        )
        return {
            **affiliate_link_payload(candidate),
            "reused": False,
            "in_progress": False,
        }

    assert result is not None
    if result.no_eligible_offer:
        candidate.affiliate_url = None
        candidate.affiliate_provider_reference = None
        candidate.affiliate_link_status = AFFILIATE_NO_ELIGIBLE_OFFER
        candidate.affiliate_link_generated_at = None
        candidate.affiliate_link_error_code = "takeads_no_eligible_offer"
        candidate.affiliate_link_error_message = (
            "Takeads did not find an eligible affiliate offer for this product URL."
        )
        _commit_or_raise(db, operation="record_no_eligible_offer")
        logger.info(
            "affiliate_link_no_eligible_offer product_id=%s provider=%s attempt=%s",
            candidate.id,
            TAKEADS_PROVIDER,
            attempt_number,
        )
        return {
            **affiliate_link_payload(candidate),
            "reused": False,
            "in_progress": False,
        }

    candidate.affiliate_url = result.tracking_link
    candidate.affiliate_provider_reference = result.returned_iri
    candidate.affiliate_link_status = AFFILIATE_READY_TO_VERIFY
    candidate.affiliate_link_generated_at = now
    candidate.affiliate_link_error_code = None
    candidate.affiliate_link_error_message = None
    _commit_or_raise(db, operation="record_generated_link")
    logger.info(
        "affiliate_link_ready_to_verify product_id=%s provider=%s attempt=%s",
        candidate.id,
        TAKEADS_PROVIDER,
        attempt_number,
    )
    return {
        **affiliate_link_payload(candidate),
        "reused": False,
        "in_progress": False,
    }


def resolve_takeads_affiliate_link(
    db: Session,
    candidate: ProductCandidate,
    *,
    force: bool = False,
    client: TakeadsClient | None = None,
) -> dict[str, Any]:
    if not candidate.id:
        raise AffiliateLinkTransitionError(
            "Candidate must be saved before an affiliate link can be generated"
        )

    started = _start_generation(db, candidate.id, force=force)
    if isinstance(started, dict):
        return started

    active_candidate, attempt_number = started
    product_url = _clean(active_candidate.merchant_url)
    sub_id = _clean(active_candidate.affiliate_sub_id)
    assert product_url is not None
    assert sub_id is not None

    try:
        result = (client or TakeadsClient()).resolve_product_url(
            product_url=product_url,
            sub_id=sub_id,
        )
    except TakeadsClientError as exc:
        return _finalize_generation(
            db,
            candidate_id=active_candidate.id,
            attempt_number=attempt_number,
            error=exc,
        )

    return _finalize_generation(
        db,
        candidate_id=active_candidate.id,
        attempt_number=attempt_number,
        result=result,
    )


def verify_candidate_affiliate_link(
    db: Session,
    candidate: ProductCandidate,
    *,
    verified_by: str,
) -> dict[str, Any]:
    if not candidate.id:
        raise AffiliateLinkTransitionError("Candidate not found")
    locked = _locked_candidate(db, candidate.id)
    current_status = _canonical_status(locked.affiliate_link_status)
    if (
        current_status == AFFILIATE_VERIFIED
        and locked.affiliate_link_verified_at is not None
        and _valid_http_url(locked.affiliate_url)
    ):
        return {**affiliate_link_payload(locked), "reused": True}
    if current_status != AFFILIATE_READY_TO_VERIFY:
        raise AffiliateLinkTransitionError(
            "Generate and inspect an affiliate link before marking it verified"
        )
    if not _valid_http_url(locked.affiliate_url):
        raise AffiliateLinkTransitionError(
            "The candidate does not have a usable generated affiliate link"
        )

    now = datetime.now(timezone.utc)
    locked.affiliate_link_status = AFFILIATE_VERIFIED
    locked.affiliate_link_verified_at = now
    locked.affiliate_link_verified_by = verified_by
    locked.affiliate_link_error_code = None
    locked.affiliate_link_error_message = None
    _commit_or_raise(db, operation="verify_link")
    logger.info(
        "affiliate_link_verified product_id=%s provider=%s curator_user_id=%s",
        locked.id,
        locked.affiliate_provider or TAKEADS_PROVIDER,
        verified_by,
    )
    return {**affiliate_link_payload(locked), "reused": False}


def invalidate_candidate_affiliate_link(
    db: Session,
    candidate: ProductCandidate,
    *,
    invalidated_by: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if not candidate.id:
        raise AffiliateLinkTransitionError("Candidate not found")
    locked = _locked_candidate(db, candidate.id)
    current_status = _canonical_status(locked.affiliate_link_status)
    if current_status not in {
        AFFILIATE_READY_TO_VERIFY,
        AFFILIATE_VERIFIED,
        AFFILIATE_INVALID,
    }:
        raise AffiliateLinkTransitionError(
            "Only a generated affiliate link can be reported invalid"
        )
    if not _valid_http_url(locked.affiliate_url):
        raise AffiliateLinkTransitionError(
            "The candidate does not have a generated affiliate link"
        )
    if _candidate_has_active_product(db, locked):
        raise AffiliateLinkTransitionError(
            "Unpublish the product before reporting its affiliate link invalid"
        )

    if current_status == AFFILIATE_INVALID:
        return {**affiliate_link_payload(locked), "reused": True}

    now = datetime.now(timezone.utc)
    locked.affiliate_link_status = AFFILIATE_INVALID
    locked.affiliate_link_verified_at = None
    locked.affiliate_link_verified_by = None
    locked.affiliate_link_invalidated_at = now
    locked.affiliate_link_invalidated_by = invalidated_by
    locked.affiliate_link_error_code = "manual_verification_failed"
    locked.affiliate_link_error_message = (
        _clean(reason)
        or "The generated affiliate link did not open the correct product."
    )
    _commit_or_raise(db, operation="invalidate_link")
    logger.warning(
        "affiliate_link_invalidated product_id=%s provider=%s curator_user_id=%s",
        locked.id,
        locked.affiliate_provider or TAKEADS_PROVIDER,
        invalidated_by,
    )
    return {**affiliate_link_payload(locked), "reused": False}


def reset_affiliate_link_after_product_url_change(
    candidate: ProductCandidate,
) -> None:
    candidate.affiliate_url = None
    candidate.affiliate_provider = None
    candidate.affiliate_provider_reference = None
    candidate.affiliate_link_status = AFFILIATE_NOT_GENERATED
    candidate.affiliate_link_error_code = None
    candidate.affiliate_link_error_message = None
    candidate.affiliate_link_last_attempted_at = None
    candidate.affiliate_link_generated_at = None
    candidate.affiliate_link_verified_at = None
    candidate.affiliate_link_verified_by = None

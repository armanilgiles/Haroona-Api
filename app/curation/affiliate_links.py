from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.models import Product, ProductCandidate


TAKEADS_RESOLVE_URL = "https://api.takeads.com/v1/product/monetize-api/v2/resolve"
TAKEADS_REQUEST_TIMEOUT_SECONDS = 15

AFFILIATE_NOT_REQUESTED = "not_requested"
AFFILIATE_GENERATED = "generated"
AFFILIATE_VERIFIED = "verified"
AFFILIATE_FAILED = "failed"

AFFILIATE_LINK_STATUSES = {
    AFFILIATE_NOT_REQUESTED,
    AFFILIATE_GENERATED,
    AFFILIATE_VERIFIED,
    AFFILIATE_FAILED,
}


class AffiliateLinkTransitionError(ValueError):
    pass


class TakeadsResolveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _valid_http_url(value: str | None) -> bool:
    cleaned = _clean(value)
    if not cleaned:
        return False
    parsed = urlparse(cleaned)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _affiliate_sub_id(candidate: ProductCandidate) -> str:
    if candidate.affiliate_sub_id:
        return candidate.affiliate_sub_id
    if not candidate.id:
        raise AffiliateLinkTransitionError(
            "Candidate must be saved before an affiliate link can be generated"
        )
    candidate.affiliate_sub_id = f"haroona-product-{candidate.id}"
    return candidate.affiliate_sub_id


def affiliate_link_payload(candidate: ProductCandidate) -> dict[str, Any]:
    return {
        "status": candidate.affiliate_link_status or AFFILIATE_NOT_REQUESTED,
        "affiliate_url": candidate.affiliate_url,
        "merchant_url": candidate.merchant_url,
        "sub_id": candidate.affiliate_sub_id,
        "error_code": candidate.affiliate_link_error_code,
        "error_message": candidate.affiliate_link_error_message,
        "last_attempted_at": candidate.affiliate_link_last_attempted_at,
        "generated_at": candidate.affiliate_link_generated_at,
        "verified_at": candidate.affiliate_link_verified_at,
        "verified_by": candidate.affiliate_link_verified_by,
    }


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

    affiliate_status = candidate.affiliate_link_status or AFFILIATE_NOT_REQUESTED
    if affiliate_status == AFFILIATE_GENERATED:
        return "affiliate_link_generated"
    if affiliate_status == AFFILIATE_VERIFIED:
        return "affiliate_link_verified"
    if affiliate_status == AFFILIATE_FAILED:
        return "affiliate_link_failed"
    return "approved"


def _error_for_status(status_code: int) -> TakeadsResolveError:
    if status_code == 400:
        return TakeadsResolveError(
            "invalid_product_url",
            "Takeads could not process this product URL. Confirm the original product link and retry.",
        )
    if status_code == 401:
        return TakeadsResolveError(
            "takeads_unauthorized",
            "Takeads rejected the backend platform key. Check TAKEADS_PLATFORM_API_KEY.",
        )
    if status_code == 403:
        return TakeadsResolveError(
            "takeads_forbidden",
            "This Takeads platform key is not allowed to monetize the product URL.",
        )
    if status_code == 429:
        return TakeadsResolveError(
            "takeads_rate_limited",
            "Takeads is receiving too many requests. Wait briefly, then retry.",
        )
    if status_code in {500, 502, 503, 504}:
        return TakeadsResolveError(
            "takeads_unavailable",
            "Takeads is temporarily unavailable. Retry in a moment.",
        )
    return TakeadsResolveError(
        "takeads_request_failed",
        f"Takeads could not generate the affiliate link (HTTP {status_code}). Retry in a moment.",
    )


def _request_takeads_link(*, product_url: str, sub_id: str) -> str:
    platform_key = _clean(os.getenv("TAKEADS_PLATFORM_API_KEY"))
    if not platform_key:
        raise TakeadsResolveError(
            "takeads_not_configured",
            "Affiliate link generation is not configured. Add TAKEADS_PLATFORM_API_KEY to the backend environment.",
        )

    try:
        response = requests.put(
            TAKEADS_RESOLVE_URL,
            headers={
                "Authorization": f"Bearer {platform_key}",
                "Content-Type": "application/json",
            },
            json={
                "iris": [product_url],
                "subId": sub_id,
                "withImages": False,
            },
            timeout=TAKEADS_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise TakeadsResolveError(
            "takeads_timeout",
            "Takeads did not respond in time. Retry the affiliate link.",
        ) from exc
    except requests.RequestException as exc:
        raise TakeadsResolveError(
            "takeads_unavailable",
            "Takeads could not be reached. Check the backend connection and retry.",
        ) from exc

    if not 200 <= response.status_code < 300:
        raise _error_for_status(response.status_code)

    try:
        body = response.json()
    except ValueError as exc:
        raise TakeadsResolveError(
            "takeads_invalid_response",
            "Takeads returned an unreadable response. Retry in a moment.",
        ) from exc

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        raise TakeadsResolveError(
            "takeads_unsupported_product",
            "Takeads could not monetize this product URL. The merchant may not be supported.",
        )

    matching_item = next(
        (
            item
            for item in data
            if isinstance(item, dict) and item.get("iri") == product_url
        ),
        data[0],
    )
    tracking_link = (
        matching_item.get("trackingLink")
        if isinstance(matching_item, dict)
        else None
    )
    if not _valid_http_url(tracking_link):
        raise TakeadsResolveError(
            "takeads_missing_tracking_link",
            "Takeads did not return a usable affiliate link for this product. Retry or check merchant support.",
        )

    return str(tracking_link).strip()


def _mark_affiliate_failure(
    candidate: ProductCandidate,
    *,
    code: str,
    message: str,
    attempted_at: datetime,
) -> None:
    candidate.affiliate_url = None
    candidate.affiliate_link_status = AFFILIATE_FAILED
    candidate.affiliate_link_error_code = code
    candidate.affiliate_link_error_message = message
    candidate.affiliate_link_last_attempted_at = attempted_at
    candidate.affiliate_link_generated_at = None
    candidate.affiliate_link_verified_at = None
    candidate.affiliate_link_verified_by = None


def resolve_takeads_affiliate_link(
    db: Session,
    candidate: ProductCandidate,
) -> dict[str, Any]:
    if candidate.review_status != "approved":
        raise AffiliateLinkTransitionError(
            "Approve the product before generating its affiliate link"
        )

    existing_status = candidate.affiliate_link_status or AFFILIATE_NOT_REQUESTED
    if (
        existing_status in {AFFILIATE_GENERATED, AFFILIATE_VERIFIED}
        and _valid_http_url(candidate.affiliate_url)
    ):
        return {**affiliate_link_payload(candidate), "reused": True}

    sub_id = _affiliate_sub_id(candidate)
    attempted_at = datetime.now(timezone.utc)
    product_url = _clean(candidate.merchant_url)
    if not _valid_http_url(product_url):
        _mark_affiliate_failure(
            candidate,
            code="invalid_product_url",
            message="The original product URL is missing or invalid. Correct it before retrying.",
            attempted_at=attempted_at,
        )
        db.commit()
        return {**affiliate_link_payload(candidate), "reused": False}

    try:
        tracking_link = _request_takeads_link(
            product_url=product_url,
            sub_id=sub_id,
        )
    except TakeadsResolveError as exc:
        _mark_affiliate_failure(
            candidate,
            code=exc.code,
            message=exc.message,
            attempted_at=attempted_at,
        )
        db.commit()
        return {**affiliate_link_payload(candidate), "reused": False}

    candidate.affiliate_url = tracking_link
    candidate.affiliate_link_status = AFFILIATE_GENERATED
    candidate.affiliate_link_error_code = None
    candidate.affiliate_link_error_message = None
    candidate.affiliate_link_last_attempted_at = attempted_at
    candidate.affiliate_link_generated_at = attempted_at
    candidate.affiliate_link_verified_at = None
    candidate.affiliate_link_verified_by = None
    db.commit()
    return {**affiliate_link_payload(candidate), "reused": False}


def verify_candidate_affiliate_link(
    db: Session,
    candidate: ProductCandidate,
    *,
    verified: bool,
    verified_by: str,
) -> dict[str, Any]:
    current_status = candidate.affiliate_link_status or AFFILIATE_NOT_REQUESTED
    if current_status not in {AFFILIATE_GENERATED, AFFILIATE_VERIFIED}:
        raise AffiliateLinkTransitionError(
            "Generate and test an affiliate link before recording verification"
        )
    if not _valid_http_url(candidate.affiliate_url):
        raise AffiliateLinkTransitionError(
            "The candidate does not have a usable generated affiliate link"
        )
    if not verified and candidate.promoted_product_id:
        active_product = (
            db.query(Product)
            .filter(Product.id == candidate.promoted_product_id)
            .filter(Product.is_active.is_(True))
            .first()
        )
        if active_product:
            raise AffiliateLinkTransitionError(
                "Unpublish the product before marking its affiliate link as incorrect"
            )

    now = datetime.now(timezone.utc)
    if verified:
        candidate.affiliate_link_status = AFFILIATE_VERIFIED
        candidate.affiliate_link_verified_at = now
        candidate.affiliate_link_verified_by = verified_by
        candidate.affiliate_link_error_code = None
        candidate.affiliate_link_error_message = None
    else:
        _mark_affiliate_failure(
            candidate,
            code="manual_verification_failed",
            message="The generated link did not open the correct product. Retry to request a new link.",
            attempted_at=candidate.affiliate_link_last_attempted_at or now,
        )

    db.commit()
    return affiliate_link_payload(candidate)


def reset_affiliate_link_after_product_url_change(
    candidate: ProductCandidate,
) -> None:
    candidate.affiliate_url = None
    candidate.affiliate_link_status = AFFILIATE_NOT_REQUESTED
    candidate.affiliate_link_error_code = None
    candidate.affiliate_link_error_message = None
    candidate.affiliate_link_last_attempted_at = None
    candidate.affiliate_link_generated_at = None
    candidate.affiliate_link_verified_at = None
    candidate.affiliate_link_verified_by = None

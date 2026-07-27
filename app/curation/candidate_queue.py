from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import exists
from sqlalchemy.orm import Query, Session

from app.curation.affiliate_links import AFFILIATE_VERIFIED
from app.curation.eligibility import INELIGIBLE, evaluate_candidate_eligibility
from app.curation.scoring import (
    HAROONA_SELECTION_THRESHOLD,
    STRICT_DISTINCTIVENESS_SCORING_MODE,
)
from app.models import Product, ProductCandidate


CANDIDATE_QUEUE_STATUSES = {
    "pending",
    "approved",
    "published",
    "rejected",
    "archived",
}


class CandidateTransitionError(ValueError):
    pass


def candidate_has_active_product():
    """Return a correlated expression for a candidate's live promoted product."""
    return (
        exists()
        .where(Product.id == ProductCandidate.promoted_product_id)
        .where(Product.is_active.is_(True))
    )


def apply_candidate_queue_filter(query: Query, status: str | None) -> Query:
    """Apply mutually exclusive Curator Studio queue semantics."""
    normalized = (status or "all").strip().lower().replace("-", "_")
    if normalized not in CANDIDATE_QUEUE_STATUSES | {"all"}:
        accepted = ", ".join(sorted(CANDIDATE_QUEUE_STATUSES))
        raise ValueError(f"Unknown candidate queue '{status}'. Use one of: {accepted}.")

    has_active_product = candidate_has_active_product()

    if normalized == "all":
        return query.filter(ProductCandidate.review_status != "archived")
    if normalized == "published":
        return query.filter(
            ProductCandidate.review_status != "archived",
            has_active_product,
        )
    if normalized == "archived":
        return query.filter(ProductCandidate.review_status == "archived")

    return query.filter(
        ProductCandidate.review_status == normalized,
        ~has_active_product,
    )


def resolve_candidate_queue_status(
    review_status: str | None,
    product_is_active: bool | None,
) -> str:
    """Resolve the single queue shown to admins, with archive taking priority."""
    normalized = (review_status or "pending").strip().lower().replace("-", "_")
    if normalized == "archived":
        return "archived"
    if product_is_active is True:
        return "published"
    return normalized


def _promoted_product(
    db: Session,
    candidate: ProductCandidate,
) -> Product | None:
    if not candidate.promoted_product_id:
        return None
    return (
        db.query(Product)
        .filter(Product.id == candidate.promoted_product_id)
        .first()
    )


def _require_pending_review_transition(
    db: Session,
    candidate: ProductCandidate,
    action: str,
) -> None:
    if candidate.review_status != "pending":
        raise CandidateTransitionError(
            f"Only pending candidates can be {action}"
        )
    promoted_product = _promoted_product(db, candidate)
    if promoted_product and promoted_product.is_active:
        raise CandidateTransitionError(
            "Live candidates must be unpublished before review changes"
        )


def _refresh_candidate_eligibility(candidate: ProductCandidate):
    result = evaluate_candidate_eligibility(
        title=candidate.title,
        affiliate_url=candidate.affiliate_url,
        merchant_url=candidate.merchant_url,
        image_url=candidate.image_url,
        availability=candidate.availability,
        normalized_category=candidate.normalized_category,
        price_amount=candidate.price_amount,
        currency=candidate.currency,
    )
    candidate.eligibility_status = result.status
    candidate.eligibility_reasons = result.reasons
    return result


def haroona_selection_failure(candidate: ProductCandidate) -> str | None:
    """Return the editorial reason a candidate cannot move toward discovery.

    Platform alignment remains visible curator context, but it is intentionally
    not part of this gate. Haroona selection is driven by the city rubric,
    required product data, and the curator's explicit decision.
    """
    if not str(candidate.target_city_slug or "").strip():
        return "A final city must be assigned before approval"

    selection_score = int(candidate.haroona_score or 0)
    if selection_score < HAROONA_SELECTION_THRESHOLD:
        return (
            f"Haroona selection score {selection_score}/100 is below the "
            f"{HAROONA_SELECTION_THRESHOLD}/100 threshold"
        )

    analysis = (
        candidate.scoring_analysis
        if isinstance(candidate.scoring_analysis, dict)
        else {}
    )
    is_strict = (
        candidate.scoring_mode == STRICT_DISTINCTIVENESS_SCORING_MODE
        or str(candidate.scoring_version or "").startswith(
            STRICT_DISTINCTIVENESS_SCORING_MODE
        )
    )
    if is_strict:
        primary_match_eligible = analysis.get("primary_match_eligible")
        if primary_match_eligible is False:
            reasons = [
                str(reason).replace("_", " ")
                for reason in (analysis.get("gate_failure_reasons") or [])
                if str(reason).strip()
            ]
            detail = f": {', '.join(reasons)}" if reasons else ""
            return f"Strict city-distinctiveness gate did not pass{detail}"
        if primary_match_eligible is not True:
            return (
                "Strict city-distinctiveness result is missing; rescore the "
                "candidate before approval"
            )

    return None


def _require_haroona_selection(
    candidate: ProductCandidate,
    action: str,
) -> None:
    failure = haroona_selection_failure(candidate)
    if failure:
        raise CandidateTransitionError(
            f"Candidate cannot be {action}: {failure}"
        )


def approve_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    reviewed_by: str,
) -> dict:
    _require_pending_review_transition(db, candidate, "approved")
    eligibility = _refresh_candidate_eligibility(candidate)
    if eligibility.status == INELIGIBLE:
        reasons = ", ".join(eligibility.blocking_reasons)
        raise CandidateTransitionError(
            f"Candidate is not eligible for approval: {reasons}"
        )
    _require_haroona_selection(candidate, "approved")
    candidate.review_status = "approved"
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.rejection_reason = None
    db.commit()
    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "review_status": candidate.review_status,
    }


def reject_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    reviewed_by: str,
    reason: str,
) -> dict:
    _require_pending_review_transition(db, candidate, "rejected")
    cleaned_reason = reason.strip()
    if len(cleaned_reason) < 3:
        raise CandidateTransitionError(
            "Rejection reason must be at least 3 characters"
        )
    candidate.review_status = "rejected"
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.rejection_reason = cleaned_reason
    db.commit()
    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "review_status": candidate.review_status,
    }


def archive_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    archived_by: str,
    reason: str,
) -> dict:
    if candidate.review_status == "archived":
        raise CandidateTransitionError("Candidate is already archived")

    now = datetime.now(timezone.utc)
    archived_product_id = candidate.promoted_product_id
    product = _promoted_product(db, candidate)
    product_was_deactivated = False
    if product:
        product_was_deactivated = bool(product.is_active)
        product.is_active = False
        product.deactivated_at = now
        product.deactivation_reason = reason
        product.availability_status = "archived"
        product.price_check_status = "curator_archive"

    candidate.review_status = "archived"
    candidate.reviewed_by = archived_by
    candidate.reviewed_at = now
    candidate.review_notes = reason
    candidate.rejection_reason = None
    db.commit()
    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "review_status": candidate.review_status,
        "promoted_product_id": archived_product_id,
        "product_was_deactivated": product_was_deactivated,
    }


def restore_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    restored_by: str,
    restore_to: str,
) -> dict:
    if candidate.review_status != "archived":
        raise CandidateTransitionError("Only archived candidates can be restored")

    normalized_target = restore_to.strip().lower().replace("-", "_")
    if normalized_target not in {"pending", "live"}:
        raise CandidateTransitionError("restore_to must be 'pending' or 'live'")

    now = datetime.now(timezone.utc)
    restored_product_id = candidate.promoted_product_id
    product = _promoted_product(db, candidate)
    product_was_reactivated = False

    if normalized_target == "live":
        if (
            candidate.affiliate_link_status != AFFILIATE_VERIFIED
            or not (candidate.affiliate_url or "").strip()
        ):
            raise CandidateTransitionError(
                "Affiliate link must be manually verified before restoring this product live"
            )
        eligibility = _refresh_candidate_eligibility(candidate)
        if eligibility.status == INELIGIBLE:
            reasons = ", ".join(eligibility.blocking_reasons)
            raise CandidateTransitionError(
                f"Candidate is not eligible to restore live: {reasons}"
            )
        _require_haroona_selection(candidate, "restored live")
        if not restored_product_id or not product:
            raise CandidateTransitionError(
                "Only previously published candidates can be restored live"
            )
        product.is_active = True
        product.deactivated_at = None
        product.deactivation_reason = None
        product.availability_status = "in_stock"
        product.price_check_status = "curator_restore"
        candidate.review_status = "approved"
        candidate.promoted_at = candidate.promoted_at or now
        product_was_reactivated = True
    else:
        if product and product.is_active:
            product.is_active = False
            product.deactivated_at = now
            product.deactivation_reason = "Restored to Pending review"
            product.availability_status = "archived"
            product.price_check_status = "curator_restore_to_review"
        candidate.review_status = "pending"

    candidate.reviewed_by = restored_by
    candidate.reviewed_at = now
    candidate.review_notes = "Restored from archive"
    candidate.rejection_reason = None
    db.commit()
    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "review_status": candidate.review_status,
        "promoted_product_id": restored_product_id,
        "product_was_reactivated": product_was_reactivated,
    }

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.curation.city_assignment import (
    CityAssignmentDecision,
    CityScanMode,
    active_scoring_city_slugs,
    build_city_assignment_decision,
    normalize_city_scan_mode,
)
from app.curation.platform_alignment import score_platform_alignment
from app.curation.scoring import (
    STRICT_DISTINCTIVENESS_SCORING_MODE,
    ScoreResult,
    score_city_fit,
)
from app.models import City, ProductCandidate


def _score_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    scoring_mode: str,
    manual_observed_garment_details: list[str],
    concept_overrides: tuple[dict[str, object], ...],
    reassign_automatically: bool,
) -> tuple[ScoreResult, CityAssignmentDecision, bool]:
    stored_mode = normalize_city_scan_mode(
        candidate.city_scan_mode or CityScanMode.SELECTED.value
    )
    preserve_final_assignment = bool(
        candidate.target_city_slug
        and not reassign_automatically
        and (
            candidate.manual_city_override
            or candidate.promoted_product_id is not None
        )
    )
    auto_mode = bool(
        reassign_automatically
        or (
            stored_mode == CityScanMode.AUTO
            and not candidate.manual_city_override
            and not preserve_final_assignment
        )
    )
    scoring_city_mode = CityScanMode.AUTO if auto_mode else stored_mode
    target_city_slug = (
        None
        if auto_mode
        else candidate.target_city_slug or candidate.recommended_city_slug
    )
    if scoring_city_mode == CityScanMode.SELECTED and not target_city_slug:
        raise ValueError("Assign a final city before rescoring this selected-city product")

    active_city_slugs = (
        active_scoring_city_slugs(db)
        if scoring_city_mode == CityScanMode.AUTO
        or stored_mode == CityScanMode.AUTO
        else ()
    )
    score = score_city_fit(
        title=candidate.title,
        description=candidate.description,
        product_type=candidate.normalized_category,
        tags=[],
        target_city_slug=target_city_slug,
        normalized_category=candidate.normalized_category,
        merchant_name=candidate.merchant_name,
        merchant_profile_allowed=candidate.merchant_verification == "verified",
        brand_name=candidate.brand_name,
        concept_overrides=concept_overrides,
        scoring_mode=(
            STRICT_DISTINCTIVENESS_SCORING_MODE
            if scoring_city_mode == CityScanMode.AUTO
            else scoring_mode
        ),
        manual_observed_garment_details=manual_observed_garment_details,
        candidate_city_slugs=active_city_slugs or None,
    )
    decision = build_city_assignment_decision(
        score,
        city_mode=scoring_city_mode,
        selected_city_slug=target_city_slug,
        active_city_slugs=active_city_slugs,
        manual_city_slug=(
            candidate.target_city_slug
            if candidate.manual_city_override and not reassign_automatically
            else None
        ),
    )

    if preserve_final_assignment and not candidate.manual_city_override:
        decision = replace(
            decision,
            final_city_slug=candidate.target_city_slug,
            city_assignment_status=candidate.city_assignment_status,
            city_assignment_source=candidate.city_assignment_source,
            manual_city_override=False,
        )
    return score, decision, preserve_final_assignment


def _apply_score_and_assignment(
    candidate: ProductCandidate,
    *,
    score: ScoreResult,
    assignment: CityAssignmentDecision,
    manual_observed_garment_details: list[str],
    rescored_by: str,
    preserve_assigned_metadata: bool,
) -> None:
    previous_final_city = candidate.target_city_slug

    candidate.city_scan_mode = assignment.city_scan_mode
    candidate.target_city_slug = assignment.final_city_slug
    candidate.recommended_city_slug = assignment.recommended_city_slug
    candidate.recommended_city_score = assignment.recommended_city_score
    candidate.runner_up_city_slug = assignment.runner_up_city_slug
    candidate.runner_up_city_score = assignment.runner_up_city_score
    candidate.city_score_margin = assignment.city_score_margin
    candidate.city_assignment_status = assignment.city_assignment_status
    candidate.city_assignment_source = assignment.city_assignment_source
    candidate.city_candidates = assignment.city_candidates
    candidate.manual_city_override = assignment.manual_city_override

    candidate.city_connection_type = score.city_connection_type
    candidate.city_connection_note = score.city_connection_note
    candidate.merchant_profile_key = score.merchant_profile_key
    candidate.city_fit_score = (
        score.city_fit_percentage
        if score.city_fit_percentage is not None
        else score.score
    )
    candidate.city_fit_scores = score.city_fit_scores or {
        assignment.recommended_city_slug: candidate.city_fit_score
    }
    candidate.secondary_city_slug = score.secondary_city_slug
    candidate.scoring_confidence = score.confidence
    candidate.scoring_method = "deterministic_rules"
    candidate.scoring_version = score.scoring_version
    candidate.scoring_mode = score.scoring_mode
    scoring_analysis = score.analysis_payload()
    scoring_analysis.update(
        {
            "rescored_by": rescored_by.strip() or "curator-studio",
            "rescored_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    candidate.scoring_analysis = scoring_analysis
    candidate.manual_observed_garment_details = list(
        manual_observed_garment_details
    )
    candidate.haroona_score = (
        score.raw_total if score.raw_total is not None else score.score
    )
    candidate.score_reasons = score.reasons

    if not preserve_assigned_metadata:
        if assignment.final_city_slug:
            if (
                previous_final_city != assignment.final_city_slug
                or candidate.city_assigned_at is None
            ):
                candidate.city_assigned_at = datetime.now(timezone.utc)
                candidate.city_assigned_by = (
                    "automatic-rescore"
                    if assignment.city_assignment_source == "automatic"
                    else rescored_by.strip() or "curator-studio"
                )
        else:
            candidate.city_assigned_at = None
            candidate.city_assigned_by = None


def _refresh_platform_alignment(
    candidate: ProductCandidate,
    *,
    score: ScoreResult,
) -> None:
    platform_alignment = score_platform_alignment(
        title=candidate.title,
        description=candidate.description,
        product_type=candidate.normalized_category,
        tags=[],
        merchant_name=candidate.merchant_name,
        brand_name=candidate.brand_name,
        merchant_verification=candidate.merchant_verification,
        image_url=candidate.image_url,
        image_quality_score=None,
        normalized_category=candidate.normalized_category,
        city_fit_score=score.raw_total if score.raw_total is not None else score.score,
    )
    candidate.platform_alignment_score = platform_alignment.score
    candidate.platform_alignment_reasons = platform_alignment.reasons


def rescore_product_candidate(
    db: Session,
    candidate: ProductCandidate,
    *,
    scoring_mode: str,
    manual_observed_garment_details: list[str],
    rescored_by: str,
    concept_overrides: tuple[dict[str, object], ...] = (),
    reassign_automatically: bool = False,
) -> ScoreResult:
    """Explicitly rescore one candidate without changing its review/live state."""
    score, assignment, preserve_assigned_metadata = _score_candidate(
        db,
        candidate,
        scoring_mode=scoring_mode,
        manual_observed_garment_details=manual_observed_garment_details,
        concept_overrides=concept_overrides,
        reassign_automatically=reassign_automatically,
    )
    _apply_score_and_assignment(
        candidate,
        score=score,
        assignment=assignment,
        manual_observed_garment_details=manual_observed_garment_details,
        rescored_by=rescored_by,
        preserve_assigned_metadata=preserve_assigned_metadata,
    )
    _refresh_platform_alignment(candidate, score=score)

    db.commit()
    db.refresh(candidate)
    return score


def assign_product_candidate_city(
    db: Session,
    candidate: ProductCandidate,
    *,
    target_city_slug: str,
    assigned_by: str,
    concept_overrides: tuple[dict[str, object], ...] = (),
) -> ScoreResult:
    cleaned_city_slug = target_city_slug.strip().lower().replace("_", "-")
    city_exists = db.query(City.id).filter(City.slug == cleaned_city_slug).first()
    if not city_exists:
        raise ValueError(f"City '{cleaned_city_slug}' does not exist")

    active_city_slugs = active_scoring_city_slugs(db)
    score = score_city_fit(
        title=candidate.title,
        description=candidate.description,
        product_type=candidate.normalized_category,
        tags=[],
        target_city_slug=cleaned_city_slug,
        normalized_category=candidate.normalized_category,
        merchant_name=candidate.merchant_name,
        merchant_profile_allowed=candidate.merchant_verification == "verified",
        brand_name=candidate.brand_name,
        concept_overrides=concept_overrides,
        scoring_mode=candidate.scoring_mode,
        manual_observed_garment_details=(
            candidate.manual_observed_garment_details or []
        ),
        candidate_city_slugs=active_city_slugs or None,
    )
    assignment = build_city_assignment_decision(
        score,
        city_mode=candidate.city_scan_mode or CityScanMode.SELECTED.value,
        selected_city_slug=cleaned_city_slug,
        active_city_slugs=active_city_slugs,
        manual_city_slug=cleaned_city_slug,
    )
    _apply_score_and_assignment(
        candidate,
        score=score,
        assignment=assignment,
        manual_observed_garment_details=list(
            candidate.manual_observed_garment_details or []
        ),
        rescored_by=assigned_by,
        preserve_assigned_metadata=False,
    )
    candidate.city_assigned_at = datetime.now(timezone.utc)
    candidate.city_assigned_by = assigned_by.strip() or "curator-studio"
    _refresh_platform_alignment(candidate, score=score)

    db.commit()
    db.refresh(candidate)
    return score

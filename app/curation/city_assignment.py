from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.curation.scoring import (
    HAROONA_SELECTION_THRESHOLD,
    SCORING_MODE_WEIGHTS,
    SUPPORTED_CITY_SLUGS,
    CityScoreDetail,
    ScoreResult,
)
from app.models import City


AUTO_ASSIGNMENT_MARGIN = 4

AUTO_ASSIGNED = "auto_assigned"
NEEDS_CITY_REVIEW = "needs_city_review"
NO_STRONG_CITY_MATCH = "no_strong_city_match"
MANUALLY_ASSIGNED = "manually_assigned"

AUTOMATIC_ASSIGNMENT = "automatic"
SELECTED_SCAN_ASSIGNMENT = "selected_scan"
MANUAL_OVERRIDE_ASSIGNMENT = "manual_override"
LEGACY_ASSIGNMENT = "legacy"

CITY_ASSIGNMENT_STATUSES = frozenset(
    {
        AUTO_ASSIGNED,
        NEEDS_CITY_REVIEW,
        NO_STRONG_CITY_MATCH,
        MANUALLY_ASSIGNED,
    }
)


class CityScanMode(str, Enum):
    AUTO = "auto"
    SELECTED = "selected"


def normalize_city_scan_mode(value: CityScanMode | str | None) -> CityScanMode:
    if isinstance(value, CityScanMode):
        return value
    normalized = str(value or CityScanMode.SELECTED.value).strip().lower()
    try:
        return CityScanMode(normalized)
    except ValueError as exc:
        raise ValueError("City scan mode must be 'auto' or 'selected'") from exc


def active_scoring_city_slugs(db: Session) -> tuple[str, ...]:
    """Return registered Haroona cities that have an active scoring profile.

    The current City model has no separate active flag. A row in the cities
    table is therefore the existing source of truth for an active destination.
    """
    registered = {
        str(slug).strip().lower()
        for (slug,) in db.query(City.slug).all()
        if str(slug or "").strip()
    }
    return tuple(slug for slug in SUPPORTED_CITY_SLUGS if slug in registered)


def _detail_analysis_payload(detail: CityScoreDetail) -> dict[str, Any]:
    component_max_points = SCORING_MODE_WEIGHTS.get(detail.scoring_mode, {})
    return {
        "scoring_mode": detail.scoring_mode,
        "scoring_version": detail.scoring_version,
        "raw_total": detail.raw_total if detail.raw_total is not None else detail.score,
        "city_fit_percentage": (
            detail.city_fit_percentage
            if detail.city_fit_percentage is not None
            else detail.score
        ),
        "distinctiveness_score": detail.distinctiveness_score,
        "distinctiveness_breakdown": detail.distinctiveness_breakdown,
        "primary_match_eligible": detail.primary_match_eligible,
        "match_type": detail.match_type,
        "gate_failure_reasons": list(detail.gate_failure_reasons),
        "observed_garment_details": list(detail.observed_garment_details),
        "distinctiveness_evidence": list(detail.distinctiveness_evidence),
        "nearest_competing_city": detail.nearest_competing_city,
        "nearest_rival_test_passed": detail.nearest_rival_test_passed,
        "comparative_reason": detail.comparative_reason,
        "marketing_language_primary": detail.marketing_language_primary,
        "recognized_concepts": list(detail.recognized_concepts),
        "component_scores": dict(detail.component_scores),
        "component_points": dict(detail.component_points),
        "component_max_points": {
            key: float(value) for key, value in component_max_points.items()
        },
        "component_reasons": {
            key: list(reasons)
            for key, reasons in detail.component_reasons.items()
        },
    }


def rank_city_candidates(
    score: ScoreResult,
    *,
    city_slugs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    details = score.destination_details or {}
    allowed = {
        str(slug).strip().lower()
        for slug in city_slugs
        if str(slug or "").strip()
    }
    ranked_details = [
        (slug, detail)
        for slug, detail in details.items()
        if not allowed or slug in allowed
    ]
    ranked_details.sort(
        key=lambda item: (
            -(item[1].raw_total if item[1].raw_total is not None else item[1].score),
            item[0],
        )
    )

    candidates: list[dict[str, Any]] = []
    for rank, (slug, detail) in enumerate(ranked_details, start=1):
        raw_score = detail.raw_total if detail.raw_total is not None else detail.score
        city_fit_score = (
            detail.city_fit_percentage
            if detail.city_fit_percentage is not None
            else detail.score
        )
        candidates.append(
            {
                "city_slug": slug,
                "score": int(raw_score),
                "city_fit_score": int(city_fit_score),
                "rank": rank,
                "confidence": detail.confidence,
                "primary_match_eligible": (
                    detail.primary_match_eligible
                    if detail.primary_match_eligible is not None
                    else detail.is_haroona_selection
                ),
                "match_type": detail.match_type,
                "score_reasons": list(detail.reasons),
                "city_connection_type": detail.city_connection_type,
                "city_connection_note": detail.city_connection_note,
                "merchant_profile_key": detail.merchant_profile_key,
                "scoring_analysis": _detail_analysis_payload(detail),
            }
        )
    return candidates


def city_candidate_for_slug(
    candidates: Iterable[dict[str, Any]] | None,
    city_slug: str | None,
) -> dict[str, Any] | None:
    normalized = str(city_slug or "").strip().lower()
    if not normalized:
        return None
    for item in candidates or ():
        if str(item.get("city_slug") or "").strip().lower() == normalized:
            return item
    return None


@dataclass(frozen=True)
class CityAssignmentDecision:
    city_scan_mode: str
    final_city_slug: str | None
    recommended_city_slug: str
    recommended_city_score: int
    runner_up_city_slug: str | None
    runner_up_city_score: int | None
    city_score_margin: int
    city_assignment_status: str
    city_assignment_source: str
    manual_city_override: bool
    city_candidates: list[dict[str, Any]]


def build_city_assignment_decision(
    score: ScoreResult,
    *,
    city_mode: CityScanMode | str,
    selected_city_slug: str | None = None,
    active_city_slugs: Iterable[str] = (),
    manual_city_slug: str | None = None,
) -> CityAssignmentDecision:
    mode = normalize_city_scan_mode(city_mode)
    candidates = rank_city_candidates(score, city_slugs=active_city_slugs)
    if not candidates:
        raise ValueError("No active Haroona city has a scoring result")

    top = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    top_score = int(top["score"])
    runner_up_score = int(runner_up["score"]) if runner_up else None
    margin = top_score - runner_up_score if runner_up_score is not None else top_score

    cleaned_manual_city = str(manual_city_slug or "").strip().lower() or None
    cleaned_selected_city = str(selected_city_slug or "").strip().lower() or None
    if cleaned_manual_city:
        final_city_slug = cleaned_manual_city
        status = MANUALLY_ASSIGNED
        source = MANUAL_OVERRIDE_ASSIGNMENT
        manual_override = True
    elif mode == CityScanMode.SELECTED:
        if not cleaned_selected_city:
            raise ValueError("A city is required for selected-city scans")
        final_city_slug = cleaned_selected_city
        status = MANUALLY_ASSIGNED
        source = SELECTED_SCAN_ASSIGNMENT
        manual_override = False
    else:
        strong_score = top_score >= HAROONA_SELECTION_THRESHOLD
        gate_passed = top.get("primary_match_eligible") is not False
        if strong_score and gate_passed and margin >= AUTO_ASSIGNMENT_MARGIN:
            final_city_slug = str(top["city_slug"])
            status = AUTO_ASSIGNED
        elif top_score < HAROONA_SELECTION_THRESHOLD:
            final_city_slug = None
            status = NO_STRONG_CITY_MATCH
        else:
            final_city_slug = None
            status = NEEDS_CITY_REVIEW
        source = AUTOMATIC_ASSIGNMENT
        manual_override = False

    return CityAssignmentDecision(
        city_scan_mode=mode.value,
        final_city_slug=final_city_slug,
        recommended_city_slug=str(top["city_slug"]),
        recommended_city_score=top_score,
        runner_up_city_slug=(
            str(runner_up["city_slug"]) if runner_up is not None else None
        ),
        runner_up_city_score=runner_up_score,
        city_score_margin=margin,
        city_assignment_status=status,
        city_assignment_source=source,
        manual_city_override=manual_override,
        city_candidates=candidates,
    )

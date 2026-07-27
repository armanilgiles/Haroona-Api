from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.curation.concept_learning import (
    extract_unknown_concept_phrases,
    load_runtime_concept_overrides,
)
from app.curation.fashion_ontology import recognize_fashion_evidence
from app.models import (
    CurationScanRun,
    CurationScanRunCandidate,
    FashionConceptProposal,
    Product,
    ProductCandidate,
)


RESOLVED_MAPPING_STATUSES = frozenset({"mapped", "created"})


def _aware_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(parsed, datetime):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_datetime(value: Any) -> str | None:
    parsed = _aware_datetime(value)
    return parsed.isoformat() if parsed else None


def _scan_candidates(
    db: Session,
    run: CurationScanRun,
) -> list[ProductCandidate]:
    member_ids = [
        candidate_id
        for (candidate_id,) in (
            db.query(CurationScanRunCandidate.candidate_id)
            .filter(CurationScanRunCandidate.scan_run_id == run.id)
            .all()
        )
    ]
    query = db.query(ProductCandidate)
    if member_ids:
        query = query.filter(
            or_(
                ProductCandidate.id.in_(member_ids),
                ProductCandidate.scan_run_id == run.id,
            )
        )
    else:
        query = query.filter(ProductCandidate.scan_run_id == run.id)
    return query.order_by(ProductCandidate.id.asc()).all()


def _candidate_scored_at(
    candidate: ProductCandidate,
    run: CurationScanRun,
) -> datetime | None:
    analysis = (
        candidate.scoring_analysis
        if isinstance(candidate.scoring_analysis, dict)
        else {}
    )
    return (
        _aware_datetime(analysis.get("rescored_at"))
        or _aware_datetime(analysis.get("scored_at"))
        or _aware_datetime(run.completed_at)
        or _aware_datetime(run.started_at)
        or _aware_datetime(candidate.created_at)
    )


def _discovery_payload(run: CurationScanRun) -> dict[str, Any]:
    summary = run.summary if isinstance(run.summary, dict) else {}
    discovery = (
        summary.get("discovery")
        if isinstance(summary.get("discovery"), dict)
        else {}
    )
    attempts = [
        {
            "method": str(attempt.get("method") or "unknown"),
            "status": str(attempt.get("status") or "unknown"),
            "detail": str(attempt.get("detail") or "No detail recorded."),
        }
        for attempt in (discovery.get("attempts") or [])
        if isinstance(attempt, dict)
    ]
    return {
        "method": discovery.get("method") or run.scanner_name,
        "fallback_used": bool(discovery.get("fallback_used")),
        "attempts": attempts,
        "failure_type": summary.get("failure_type"),
        "failure_reason": run.error_message,
    }


def build_scan_observability(
    db: Session,
    run: CurationScanRun,
) -> dict[str, Any]:
    """Build the read-only Batch 6 explanation layer for one scan.

    The payload reflects the current reviewed ontology while retaining enough
    score timestamps to warn when a mapping decision happened later. It never
    rescales candidates or mutates published products.
    """
    candidates = _scan_candidates(db, run)
    candidate_keys = {
        candidate.id: f"{candidate.source}:{candidate.external_product_id}"
        for candidate in candidates
    }
    keys_to_candidate = {
        candidate_keys[candidate.id]: candidate
        for candidate in candidates
    }

    proposals = db.query(FashionConceptProposal).all() if candidates else []
    related_proposals: list[FashionConceptProposal] = []
    candidate_key_set = set(keys_to_candidate)
    for proposal in proposals:
        if candidate_key_set.intersection(str(key) for key in (proposal.candidate_keys or [])):
            related_proposals.append(proposal)
    proposals_by_phrase = {
        proposal.normalized_phrase: proposal for proposal in related_proposals
    }

    product_ids = [
        candidate.promoted_product_id
        for candidate in candidates
        if candidate.promoted_product_id
    ]
    product_active_by_id = {
        product.id: bool(product.is_active)
        for product in (
            db.query(Product).filter(Product.id.in_(product_ids)).all()
            if product_ids
            else []
        )
    }

    mapping_warnings_by_proposal: dict[int, dict[str, Any]] = {}
    warning_candidate_ids: set[int] = set()
    for proposal in related_proposals:
        if proposal.status not in RESOLVED_MAPPING_STATUSES:
            continue
        reviewed_at = _aware_datetime(proposal.reviewed_at)
        if reviewed_at is None:
            continue
        affected_keys = candidate_key_set.intersection(
            str(key) for key in (proposal.candidate_keys or [])
        )
        for candidate_key in affected_keys:
            candidate = keys_to_candidate[candidate_key]
            scored_at = _candidate_scored_at(candidate, run)
            if scored_at is not None and reviewed_at <= scored_at:
                continue
            warning_candidate_ids.add(candidate.id)
            warning = mapping_warnings_by_proposal.setdefault(
                proposal.id,
                {
                    "proposal_id": proposal.id,
                    "phrase": proposal.display_phrase,
                    "status": proposal.status,
                    "resolved_concept_id": proposal.resolved_concept_id,
                    "reviewed_at": reviewed_at.isoformat(),
                    "affected_candidate_ids": [],
                    "published_candidate_ids": [],
                    "requires_explicit_rescore": True,
                },
            )
            warning["affected_candidate_ids"].append(candidate.id)
            if (
                candidate.promoted_product_id
                and product_active_by_id.get(candidate.promoted_product_id)
            ):
                warning["published_candidate_ids"].append(candidate.id)

    concept_overrides = load_runtime_concept_overrides(db)
    recognized_counts: dict[tuple[str, str], int] = {}
    unknown_counts: dict[str, int] = {}
    candidate_payloads: list[dict[str, Any]] = []
    recognized_signal_count = 0
    unknown_signal_count = 0
    manually_rescored_count = 0
    last_rescored_at: datetime | None = None

    for candidate in candidates:
        evidence_text = " ".join(
            part
            for part in (
                candidate.title,
                candidate.description,
                candidate.normalized_category,
            )
            if part
        )
        evidence = recognize_fashion_evidence(
            evidence_text,
            brand_name=candidate.brand_name or candidate.merchant_name,
            concept_overrides=concept_overrides,
        )
        recognized = [
            {
                "concept_id": concept.concept_id,
                "label": concept.label,
                "category": concept.category,
                "matched_phrase": concept.matched_phrase,
            }
            for concept in evidence.concepts
        ]
        unknown_phrases = extract_unknown_concept_phrases(
            candidate.title,
            brand_name=candidate.brand_name or candidate.merchant_name,
            concept_overrides=concept_overrides,
        )
        for concept in recognized:
            key = (concept["label"], concept["category"])
            recognized_counts[key] = recognized_counts.get(key, 0) + 1
        for phrase in unknown_phrases:
            unknown_counts[phrase] = unknown_counts.get(phrase, 0) + 1
        recognized_signal_count += len(recognized)
        unknown_signal_count += len(unknown_phrases)

        analysis = (
            candidate.scoring_analysis
            if isinstance(candidate.scoring_analysis, dict)
            else {}
        )
        rescored_at = _aware_datetime(analysis.get("rescored_at"))
        if rescored_at:
            manually_rescored_count += 1
            if last_rescored_at is None or rescored_at > last_rescored_at:
                last_rescored_at = rescored_at

        product_is_active = bool(
            candidate.promoted_product_id
            and product_active_by_id.get(candidate.promoted_product_id)
        )
        if candidate.id in warning_candidate_ids:
            scoring_status = "mapping_changed_rescore_recommended"
        elif rescored_at:
            scoring_status = "manually_rescored"
        else:
            scoring_status = "scored_during_scan"

        total_signals = len(recognized) + len(unknown_phrases)
        candidate_payloads.append(
            {
                "candidate_id": candidate.id,
                "title": candidate.title,
                "recognized_concepts": recognized,
                "unrecognized_phrases": unknown_phrases,
                "ontology_coverage_percent": (
                    round(len(recognized) / total_signals * 100)
                    if total_signals
                    else None
                ),
                "scoring_version": candidate.scoring_version,
                "scoring_status": scoring_status,
                "last_scored_at": _iso_datetime(
                    analysis.get("rescored_at")
                    or analysis.get("scored_at")
                    or run.completed_at
                    or run.started_at
                ),
                "product_is_active": product_is_active,
                "published_product_changed": False,
            }
        )

    signal_total = recognized_signal_count + unknown_signal_count
    recognized_concepts = [
        {
            "label": label,
            "category": category,
            "candidate_count": count,
        }
        for (label, category), count in sorted(
            recognized_counts.items(),
            key=lambda item: (-item[1], item[0][0].lower()),
        )
    ]
    unrecognized_phrases = []
    for phrase, count in sorted(
        unknown_counts.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        proposal = proposals_by_phrase.get(phrase)
        unrecognized_phrases.append(
            {
                "phrase": phrase,
                "candidate_count": count,
                "review_status": proposal.status if proposal else "unreviewed",
                "resolved_concept_id": (
                    proposal.resolved_concept_id if proposal else None
                ),
            }
        )

    active_published_count = sum(
        1
        for candidate in candidates
        if candidate.promoted_product_id
        and product_active_by_id.get(candidate.promoted_product_id)
    )
    inactive_linked_count = sum(
        1
        for candidate in candidates
        if candidate.promoted_product_id
        and not product_active_by_id.get(candidate.promoted_product_id)
    )

    mapping_warnings = list(mapping_warnings_by_proposal.values())
    for warning in mapping_warnings:
        warning["affected_candidate_ids"].sort()
        warning["published_candidate_ids"].sort()
    mapping_warnings.sort(
        key=lambda item: (
            item["reviewed_at"] or "",
            item["phrase"].lower(),
        ),
        reverse=True,
    )

    return {
        "scan_run_id": run.id,
        "status": run.status,
        "discovery": _discovery_payload(run),
        "ontology": {
            "coverage_percent": (
                round(recognized_signal_count / signal_total * 100)
                if signal_total
                else None
            ),
            "recognized_signal_count": recognized_signal_count,
            "unrecognized_signal_count": unknown_signal_count,
            "recognized_concepts": recognized_concepts,
            "unrecognized_phrases": unrecognized_phrases,
            "basis": "current_reviewed_ontology",
        },
        "rescoring": {
            "candidate_count": len(candidates),
            "current_count": len(candidates) - len(warning_candidate_ids),
            "rescore_recommended_count": len(warning_candidate_ids),
            "manually_rescored_count": manually_rescored_count,
            "last_rescored_at": (
                last_rescored_at.isoformat() if last_rescored_at else None
            ),
        },
        "mapping_change_warnings": mapping_warnings,
        "published_product_safety": {
            "status": (
                "protected"
                if active_published_count
                else "no_live_products"
            ),
            "active_published_count": active_published_count,
            "inactive_linked_count": inactive_linked_count,
            "published_products_changed": False,
            "message": (
                "Concept mappings and rescoring never change or unpublish a "
                "live product automatically."
            ),
        },
        "candidates": candidate_payloads,
    }

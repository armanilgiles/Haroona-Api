from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.curation.fashion_ontology import (
    concept_definition_by_id,
    concept_definitions,
    normalize_fashion_text,
)
from app.models import (
    FashionConcept,
    FashionConceptAlias,
    FashionConceptProposal,
    ProductCandidate,
)


CONCEPT_CATEGORIES = (
    "aesthetic",
    "color",
    "construction_detail",
    "garment_type",
    "material",
    "material_property",
    "occasion",
    "pattern",
    "silhouette",
    "surface_design",
)

_STOP_WORDS = {
    "about", "after", "also", "available", "best", "black", "brand",
    "collection", "color", "design", "designer", "detail", "dress",
    "edition", "exclusive", "fashion", "from", "great", "ladies", "made",
    "model", "online", "piece", "product", "sale", "shop", "size", "style",
    "this", "with", "women", "womens", "your",
}


def normalize_concept_phrase(value: str | None) -> str:
    return normalize_fashion_text(value).strip()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _normalize_trait(value: str) -> str:
    return _slugify(value)


def _custom_concept_definition(row: FashionConcept, aliases: list[str]) -> dict[str, Any]:
    return {
        "id": row.concept_id,
        "label": row.label,
        "category": row.category,
        "aliases": aliases,
        "traits": [str(item) for item in (row.traits or [])],
    }


def load_runtime_concept_overrides(db: Session) -> tuple[dict[str, Any], ...]:
    aliases = (
        db.query(FashionConceptAlias)
        .filter(FashionConceptAlias.active.is_(True))
        .order_by(FashionConceptAlias.id.asc())
        .all()
    )
    custom_rows = (
        db.query(FashionConcept)
        .filter(FashionConcept.active.is_(True))
        .all()
    )
    custom_by_id = {row.concept_id: row for row in custom_rows}
    phrases_by_concept: dict[str, list[str]] = {}
    for alias in aliases:
        phrases_by_concept.setdefault(alias.concept_id, []).append(alias.display_phrase)

    overrides: list[dict[str, Any]] = []
    for concept_id, phrases in phrases_by_concept.items():
        built_in = concept_definition_by_id(concept_id)
        if built_in:
            overrides.append(
                {
                    "id": built_in["id"],
                    "label": built_in["label"],
                    "category": built_in["category"],
                    "aliases": phrases,
                    "traits": list(built_in.get("traits") or []),
                }
            )
            continue
        custom = custom_by_id.get(concept_id)
        if custom:
            overrides.append(_custom_concept_definition(custom, phrases))

    return tuple(overrides)


def list_available_concepts(
    db: Session,
    *,
    search: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    needle = normalize_concept_phrase(search)
    items = [
        {
            "concept_id": str(item["id"]),
            "label": str(item["label"]),
            "category": str(item["category"]),
            "traits": [str(trait) for trait in (item.get("traits") or [])],
            "source": "built_in",
        }
        for item in concept_definitions()
    ]
    items.extend(
        {
            "concept_id": row.concept_id,
            "label": row.label,
            "category": row.category,
            "traits": [str(trait) for trait in (row.traits or [])],
            "source": "custom",
        }
        for row in (
            db.query(FashionConcept)
            .filter(FashionConcept.active.is_(True))
            .all()
        )
    )
    if needle:
        items = [
            item
            for item in items
            if needle in normalize_concept_phrase(
                f"{item['concept_id']} {item['label']} {item['category']}"
            )
        ]
    items.sort(key=lambda item: (item["category"], item["label"].lower()))
    return items[:limit]


def _known_tokens(concept_overrides: tuple[dict[str, Any], ...]) -> set[str]:
    known: set[str] = set()
    for concept in (*concept_definitions(), *concept_overrides):
        phrases = [
            concept.get("id"),
            concept.get("label"),
            *(concept.get("aliases") or []),
            *(concept.get("traits") or []),
        ]
        for phrase in phrases:
            known.update(normalize_concept_phrase(str(phrase or "")).split())
    return known


def extract_unknown_concept_phrases(
    title: str,
    *,
    brand_name: str | None = None,
    concept_overrides: tuple[dict[str, Any], ...] = (),
    limit: int = 6,
) -> list[str]:
    """Return conservative title terms that the reviewed ontology cannot explain.

    This is intentionally deterministic. It proposes terms for a human; it does
    not attach traits or change a score.
    """
    known = _known_tokens(concept_overrides)
    brand_tokens = set(normalize_concept_phrase(brand_name).split())
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", title or "")
    proposals: list[str] = []
    for index, raw in enumerate(raw_tokens):
        token = normalize_concept_phrase(raw)
        if (
            not token
            or token in known
            or token in brand_tokens
            or token in _STOP_WORDS
            or token in proposals
        ):
            continue
        # Product names are commonly the first title token. Keep a first token
        # only when its morphology looks like an actual descriptive fashion term.
        if index == 0 and raw[:1].isupper() and not token.endswith(
            ("ed", "ing", "al", "ic", "ous", "less", "ful", "core", "wear")
        ):
            continue
        proposals.append(token)
        if len(proposals) >= limit:
            break
    return proposals


def proposal_payload(row: FashionConceptProposal) -> dict[str, Any]:
    return {
        "id": row.id,
        "phrase": row.display_phrase,
        "normalized_phrase": row.normalized_phrase,
        "status": row.status,
        "occurrence_count": row.occurrence_count,
        "examples": list(row.examples or []),
        "resolved_concept_id": row.resolved_concept_id,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
    }


def _record_unknown_concepts_once(db: Session, scan_run_id: str) -> dict[str, int]:
    concept_overrides = load_runtime_concept_overrides(db)
    candidates = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.scan_run_id == scan_run_id)
        .all()
    )
    detected = 0
    now = datetime.now(timezone.utc)
    observations: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        candidate_key = f"{candidate.source}:{candidate.external_product_id}"
        phrases = extract_unknown_concept_phrases(
            candidate.title,
            brand_name=candidate.brand_name or candidate.merchant_name,
            concept_overrides=concept_overrides,
        )
        for phrase in phrases:
            detected += 1
            observation = observations.setdefault(
                phrase,
                {"candidate_keys": [], "examples": []},
            )
            if candidate_key in observation["candidate_keys"]:
                continue
            observation["candidate_keys"].append(candidate_key)
            if len(observation["examples"]) < 8:
                observation["examples"].append(
                    {
                        "candidate_id": candidate.id,
                        "title": candidate.title,
                        "merchant_name": candidate.merchant_name,
                        "source_url": candidate.source_url,
                    }
                )
    if not observations:
        return {"detected": detected, "created": 0, "updated": 0}

    existing_rows = (
        db.query(FashionConceptProposal)
        .filter(FashionConceptProposal.normalized_phrase.in_(observations))
        .all()
    )
    rows_by_phrase = {row.normalized_phrase: row for row in existing_rows}
    created = 0
    updated = 0

    for phrase, observation in observations.items():
        row = rows_by_phrase.get(phrase)
        if row and row.status != "pending":
            continue
        is_new = row is None
        if is_new:
            row = FashionConceptProposal(
                normalized_phrase=phrase,
                display_phrase=phrase,
                status="pending",
                occurrence_count=0,
                examples=[],
                candidate_keys=[],
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            rows_by_phrase[phrase] = row

        keys = list(row.candidate_keys or [])
        new_keys = [
            key for key in observation["candidate_keys"] if key not in keys
        ]
        if not new_keys:
            continue
        keys.extend(new_keys)
        examples = list(row.examples or [])
        remaining_slots = max(0, 8 - len(examples))
        if remaining_slots:
            examples.extend(observation["examples"][:remaining_slots])
        row.candidate_keys = keys[-1000:]
        row.examples = examples
        row.occurrence_count = len(row.candidate_keys)
        row.last_seen_at = now
        if is_new:
            created += 1
        else:
            updated += 1

    db.commit()
    return {"detected": detected, "created": created, "updated": updated}


def record_unknown_concepts_for_scan(db: Session, scan_run_id: str) -> dict[str, int]:
    """Record review proposals without allowing duplicate phrases in one batch.

    Production sessions disable autoflush, so querying once per candidate can stage
    the same unique phrase several times before the INSERT occurs. Aggregate first,
    then retry once if a concurrent scan creates a phrase between SELECT and COMMIT.
    """
    for attempt in range(2):
        try:
            return _record_unknown_concepts_once(db, scan_run_id)
        except IntegrityError:
            db.rollback()
            if attempt == 1:
                raise
    raise RuntimeError("Concept proposal recording retry was exhausted")


def _get_pending_proposal(db: Session, proposal_id: int) -> FashionConceptProposal:
    row = (
        db.query(FashionConceptProposal)
        .filter(FashionConceptProposal.id == proposal_id)
        .first()
    )
    if row is None:
        raise LookupError("Concept proposal not found")
    if row.status != "pending":
        raise ValueError("This concept proposal has already been reviewed")
    return row


def _concept_exists(db: Session, concept_id: str) -> bool:
    if concept_definition_by_id(concept_id):
        return True
    return (
        db.query(FashionConcept.id)
        .filter(
            FashionConcept.concept_id == concept_id,
            FashionConcept.active.is_(True),
        )
        .first()
        is not None
    )


def _attach_alias(
    db: Session,
    *,
    proposal: FashionConceptProposal,
    concept_id: str,
    reviewed_by: str,
) -> None:
    alias = (
        db.query(FashionConceptAlias)
        .filter(
            FashionConceptAlias.normalized_phrase == proposal.normalized_phrase
        )
        .first()
    )
    if alias and alias.concept_id != concept_id:
        raise ValueError("That phrase is already mapped to another concept")
    if alias:
        alias.active = True
        alias.display_phrase = proposal.display_phrase
    else:
        db.add(
            FashionConceptAlias(
                normalized_phrase=proposal.normalized_phrase,
                display_phrase=proposal.display_phrase,
                concept_id=concept_id,
                source="proposal_review",
                active=True,
                created_by=reviewed_by,
            )
        )


def map_proposal_to_concept(
    db: Session,
    proposal_id: int,
    *,
    concept_id: str,
    reviewed_by: str,
) -> FashionConceptProposal:
    concept_id = _slugify(concept_id)
    if not _concept_exists(db, concept_id):
        raise ValueError("The selected concept does not exist")
    proposal = _get_pending_proposal(db, proposal_id)
    _attach_alias(
        db,
        proposal=proposal,
        concept_id=concept_id,
        reviewed_by=reviewed_by,
    )
    proposal.status = "mapped"
    proposal.resolved_concept_id = concept_id
    proposal.reviewed_by = reviewed_by
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_concept_from_proposal(
    db: Session,
    proposal_id: int,
    *,
    label: str,
    category: str,
    traits: list[str],
    reviewed_by: str,
    concept_id: str | None = None,
) -> FashionConceptProposal:
    category = category.strip().lower()
    if category not in CONCEPT_CATEGORIES:
        raise ValueError("Choose a supported fashion concept category")
    clean_label = " ".join(label.split())
    resolved_id = _slugify(concept_id or clean_label)
    if not clean_label or not resolved_id:
        raise ValueError("Concept label is required")
    if _concept_exists(db, resolved_id):
        raise ValueError("A concept with that identifier already exists")
    proposal = _get_pending_proposal(db, proposal_id)
    clean_traits = list(
        dict.fromkeys(
            normalized
            for normalized in (_normalize_trait(item) for item in traits)
            if normalized
        )
    )
    db.add(
        FashionConcept(
            concept_id=resolved_id,
            label=clean_label,
            category=category,
            traits=clean_traits,
            active=True,
            created_by=reviewed_by,
        )
    )
    _attach_alias(
        db,
        proposal=proposal,
        concept_id=resolved_id,
        reviewed_by=reviewed_by,
    )
    proposal.status = "created"
    proposal.resolved_concept_id = resolved_id
    proposal.reviewed_by = reviewed_by
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal


def reject_concept_proposal(
    db: Session,
    proposal_id: int,
    *,
    reviewed_by: str,
) -> FashionConceptProposal:
    proposal = _get_pending_proposal(db, proposal_id)
    proposal.status = "rejected"
    proposal.reviewed_by = reviewed_by
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal

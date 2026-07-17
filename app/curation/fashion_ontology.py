from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


ONTOLOGY_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "fashion_scoring_ontology_v1.json"
)


def normalize_fashion_text(value: str | None) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip() + " "


@dataclass(frozen=True)
class RecognizedConcept:
    concept_id: str
    label: str
    category: str
    matched_phrase: str
    traits: tuple[str, ...]


@dataclass(frozen=True)
class RecognizedBrand:
    key: str
    origin: str | None
    strength: float
    affinities: dict[str, float]


@dataclass(frozen=True)
class FashionEvidence:
    concepts: tuple[RecognizedConcept, ...]
    traits: frozenset[str]
    trait_evidence: dict[str, tuple[str, ...]]
    brand: RecognizedBrand | None

    @property
    def concept_ids(self) -> frozenset[str]:
        return frozenset(item.concept_id for item in self.concepts)

    @property
    def material_confirmed(self) -> bool:
        return any(
            item.category == "material"
            for item in self.concepts
        )


@lru_cache(maxsize=1)
def load_fashion_ontology() -> dict[str, Any]:
    data = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    counts = data.get("counts") or {}
    concepts = data.get("concepts") or []
    aliases = sum(len(item.get("aliases") or []) for item in concepts)
    calibration = data.get("calibration_garments") or []
    if len(concepts) != counts.get("canonical_concepts"):
        raise ValueError("Fashion ontology canonical-concept count is invalid")
    if aliases != counts.get("aliases_and_related_phrases"):
        raise ValueError("Fashion ontology alias count is invalid")
    if len(calibration) != counts.get("calibration_garments"):
        raise ValueError("Fashion ontology calibration count is invalid")
    return data


@lru_cache(maxsize=1)
def _concept_phrase_index() -> tuple[tuple[str, dict[str, Any]], ...]:
    phrases: list[tuple[str, dict[str, Any]]] = []
    for concept in load_fashion_ontology()["concepts"]:
        candidates = [concept["label"], *(concept.get("aliases") or [])]
        normalized_candidates = {
            normalize_fashion_text(candidate).strip()
            for candidate in candidates
            if normalize_fashion_text(candidate).strip()
        }
        for phrase in normalized_candidates:
            phrases.append((phrase, concept))
    phrases.sort(key=lambda item: (-len(item[0].split()), -len(item[0]), item[0]))
    return tuple(phrases)


@lru_cache(maxsize=1)
def _brand_phrase_index() -> tuple[tuple[str, dict[str, Any]], ...]:
    phrases: list[tuple[str, dict[str, Any]]] = []
    for brand in load_fashion_ontology().get("brands") or []:
        candidates = [brand["key"].replace("-", " "), *(brand.get("aliases") or [])]
        for candidate in candidates:
            normalized = normalize_fashion_text(candidate).strip()
            if normalized:
                phrases.append((normalized, brand))
    phrases.sort(key=lambda item: (-len(item[0].split()), -len(item[0]), item[0]))
    return tuple(phrases)


def _contains(normalized_text: str, normalized_phrase: str) -> bool:
    return f" {normalized_phrase} " in normalized_text


def recognize_fashion_evidence(
    text: str,
    *,
    brand_name: str | None = None,
) -> FashionEvidence:
    normalized_text = normalize_fashion_text(text)
    found: dict[str, RecognizedConcept] = {}
    for phrase, concept in _concept_phrase_index():
        concept_id = str(concept["id"])
        if concept_id in found or not _contains(normalized_text, phrase):
            continue
        traits = set(str(item) for item in concept.get("traits") or [])
        traits.update(
            token
            for token in concept_id.split("_")
            if len(token) >= 4 and token not in {"dress", "shirt", "style", "fabric"}
        )
        found[concept_id] = RecognizedConcept(
            concept_id=concept_id,
            label=str(concept["label"]),
            category=str(concept["category"]),
            matched_phrase=phrase,
            traits=tuple(sorted(traits)),
        )

    all_brand_text = normalize_fashion_text(f"{brand_name or ''} {text}")
    recognized_brand: RecognizedBrand | None = None
    for phrase, brand in _brand_phrase_index():
        if not _contains(all_brand_text, phrase):
            continue
        recognized_brand = RecognizedBrand(
            key=str(brand["key"]),
            origin=str(brand["origin"]) if brand.get("origin") else None,
            strength=float(brand.get("strength") or 0),
            affinities={
                str(key): float(value)
                for key, value in (brand.get("affinities") or {}).items()
            },
        )
        break

    trait_evidence_lists: dict[str, list[str]] = {}
    for concept in found.values():
        for trait in concept.traits:
            trait_evidence_lists.setdefault(trait, []).append(concept.label)
    trait_evidence = {
        trait: tuple(dict.fromkeys(labels))
        for trait, labels in trait_evidence_lists.items()
    }
    return FashionEvidence(
        concepts=tuple(sorted(found.values(), key=lambda item: item.concept_id)),
        traits=frozenset(trait_evidence),
        trait_evidence=trait_evidence,
        brand=recognized_brand,
    )


def ontology_counts() -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in load_fashion_ontology()["counts"].items()
    }


def destination_profiles() -> dict[str, dict[str, Any]]:
    return load_fashion_ontology()["destinations"]


def calibration_garments() -> list[dict[str, Any]]:
    return load_fashion_ontology()["calibration_garments"]

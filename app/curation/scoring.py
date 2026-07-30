from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Iterable

from app.curation.fashion_ontology import (
    FashionEvidence,
    destination_profiles,
    load_fashion_ontology,
    recognize_fashion_evidence,
)
from app.curation.merchant_profiles import get_merchant_profile


LEGACY_SCORING_MODE = "legacy"
STRICT_DISTINCTIVENESS_SCORING_MODE = "strict_distinctiveness"
HYBRID_SCORING_VERSION = str(load_fashion_ontology()["scoring_version"])
STRICT_DISTINCTIVENESS_SCORING_VERSION = "strict_distinctiveness_v2"
HAROONA_SELECTION_THRESHOLD = 80
HYBRID_COMPONENT_WEIGHTS: dict[str, Decimal] = {
    "visual_aesthetic": Decimal("35"),
    "climate_practicality": Decimal("30"),
    "lifestyle_occasion": Decimal("20"),
    "distinctive_enhancement": Decimal("15"),
}
STRICT_COMPONENT_WEIGHTS: dict[str, Decimal] = {
    "visual_aesthetic": Decimal("30"),
    "climate_practicality": Decimal("25"),
    "lifestyle_occasion": Decimal("20"),
    "distinctive_enhancement": Decimal("25"),
}
SCORING_MODE_WEIGHTS = {
    LEGACY_SCORING_MODE: HYBRID_COMPONENT_WEIGHTS,
    STRICT_DISTINCTIVENESS_SCORING_MODE: STRICT_COMPONENT_WEIGHTS,
}
SCORING_MODE_VERSIONS = {
    LEGACY_SCORING_MODE: HYBRID_SCORING_VERSION,
    STRICT_DISTINCTIVENESS_SCORING_MODE: STRICT_DISTINCTIVENESS_SCORING_VERSION,
}
STRICT_SPECIFIC_EVIDENCE_CATEGORIES = frozenset(
    {
        "construction_detail",
        "material",
        "material_property",
        "color",
        "silhouette",
        "pattern",
        "surface_design",
    }
)
NON_MARKETING_EVIDENCE_SOURCES = frozenset(
    {"product_image", "manual_curator_observation"}
)

SUPPORTED_CITY_SLUGS = tuple(destination_profiles().keys())
DESTINATION_ALIASES = {
    "florence": "tuscany",
    "amalfi": "tuscany",
    "mykonos": "greek-islands",
    "santorini": "greek-islands",
}


@dataclass(frozen=True)
class ComponentScore:
    score: Decimal
    weighted_points: Decimal
    reasons: list[str]


@dataclass(frozen=True)
class GarmentEvidenceItem:
    detail: str
    source: str
    category: str
    traits: tuple[str, ...]
    marketing_copy: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "source": self.source,
            "category": self.category,
            "marketing_copy": self.marketing_copy,
        }


@dataclass(frozen=True)
class CityScoreDetail:
    score: int
    reasons: list[str]
    confidence: int
    component_scores: dict[str, float]
    component_points: dict[str, float]
    component_reasons: dict[str, list[str]]
    tier: str
    is_haroona_selection: bool
    assumptions: list[str]
    evidence_gaps: list[str]
    display_name: str
    destination_type: str
    city_connection_type: str | None = None
    city_connection_note: str | None = None
    merchant_profile_key: str | None = None
    recognized_concepts: tuple[str, ...] = ()
    scoring_mode: str = LEGACY_SCORING_MODE
    scoring_version: str = HYBRID_SCORING_VERSION
    raw_total: int | None = None
    city_fit_percentage: int | None = None
    distinctiveness_score: int | None = None
    distinctiveness_breakdown: dict[str, int] | None = None
    primary_match_eligible: bool | None = None
    match_type: str | None = None
    gate_failure_reasons: tuple[str, ...] = ()
    observed_garment_details: tuple[str, ...] = ()
    distinctiveness_evidence: tuple[dict[str, object], ...] = ()
    nearest_competing_city: str | None = None
    nearest_rival_test_passed: bool | None = None
    comparative_reason: str | None = None
    marketing_language_primary: bool | None = None


@dataclass(frozen=True)
class ScoreResult:
    score: int
    reasons: list[str]
    city_connection_type: str | None = None
    city_connection_note: str | None = None
    merchant_profile_key: str | None = None
    city_fit_scores: dict[str, int] | None = None
    secondary_city_slug: str | None = None
    confidence: int | None = None
    recommended_city_slug: str | None = None
    destination_details: dict[str, CityScoreDetail] | None = None
    season: str | None = None
    occasion: str | None = None
    scoring_mode: str = LEGACY_SCORING_MODE
    scoring_version: str = HYBRID_SCORING_VERSION
    raw_total: int | None = None
    city_fit_percentage: int | None = None
    distinctiveness_score: int | None = None
    distinctiveness_breakdown: dict[str, int] | None = None
    primary_match_eligible: bool | None = None
    match_type: str | None = None
    gate_failure_reasons: tuple[str, ...] = ()
    observed_garment_details: tuple[str, ...] = ()
    distinctiveness_evidence: tuple[dict[str, object], ...] = ()
    nearest_competing_city: str | None = None
    nearest_rival_test_passed: bool | None = None
    comparative_reason: str | None = None
    marketing_language_primary: bool | None = None
    recognized_concepts: tuple[str, ...] = ()

    def analysis_payload(self) -> dict[str, object]:
        return {
            "scoring_mode": self.scoring_mode,
            "scoring_version": self.scoring_version,
            "raw_total": self.raw_total if self.raw_total is not None else self.score,
            "city_fit_percentage": (
                self.city_fit_percentage
                if self.city_fit_percentage is not None
                else self.score
            ),
            "distinctiveness_score": self.distinctiveness_score,
            "distinctiveness_breakdown": self.distinctiveness_breakdown,
            "primary_match_eligible": self.primary_match_eligible,
            "match_type": self.match_type,
            "gate_failure_reasons": list(self.gate_failure_reasons),
            "observed_garment_details": list(self.observed_garment_details),
            "distinctiveness_evidence": list(self.distinctiveness_evidence),
            "nearest_competing_city": self.nearest_competing_city,
            "nearest_rival_test_passed": self.nearest_rival_test_passed,
            "comparative_reason": self.comparative_reason,
            "marketing_language_primary": self.marketing_language_primary,
            "recognized_concepts": list(self.recognized_concepts),
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }


def _clamp(value: Decimal, lower: str = "1.0", upper: str = "10.0") -> Decimal:
    return max(Decimal(lower), min(Decimal(upper), value))


def _one_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def normalize_scoring_mode(value: str | None) -> str:
    normalized = (value or LEGACY_SCORING_MODE).strip().lower().replace("-", "_")
    if normalized not in SCORING_MODE_WEIGHTS:
        raise ValueError(f"Unsupported scoring mode: {value}")
    return normalized


def scoring_profile_payload(scoring_mode: str) -> dict[str, object]:
    mode = normalize_scoring_mode(scoring_mode)
    weights = SCORING_MODE_WEIGHTS[mode]
    return {
        "scoring_mode": mode,
        "scoring_version": SCORING_MODE_VERSIONS[mode],
        "rubric_weights": {
            "visual_compatibility": int(weights["visual_aesthetic"]),
            "climate_compatibility": int(weights["climate_practicality"]),
            "lifestyle_compatibility": int(weights["lifestyle_occasion"]),
            "distinctiveness": int(weights["distinctive_enhancement"]),
        },
        "primary_match_gate_enabled": (
            mode == STRICT_DISTINCTIVENESS_SCORING_MODE
        ),
    }


def _component(
    name: str,
    raw_score: Decimal,
    reasons: list[str],
    *,
    component_weights: dict[str, Decimal] | None = None,
) -> ComponentScore:
    weights = component_weights or HYBRID_COMPONENT_WEIGHTS
    score = _one_decimal(_clamp(raw_score))
    weighted_points = _one_decimal(
        score * weights[name] / Decimal("10")
    )
    return ComponentScore(
        score=score,
        weighted_points=weighted_points,
        reasons=reasons,
    )


def _score_tier(score: int) -> str:
    if score >= 90:
        return "Dream / Signature Match"
    if score >= HAROONA_SELECTION_THRESHOLD:
        return "Excellent / Haroona Selection"
    if score >= 70:
        return "Solid / Consider"
    if score >= 60:
        return "Workable"
    return "Weak"


def _normalize_option(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _inferred_traits(
    evidence: FashionEvidence,
    *,
    normalized_category: str | None,
    product_type: str | None,
) -> set[str]:
    traits = set(evidence.traits)
    category_text = f"{normalized_category or ''} {product_type or ''}".lower()
    if "dress" in category_text:
        traits.update({"garment", "versatile", "day_to_night"})
    if any(value in category_text for value in ("bag", "shoe", "accessor")):
        traits.update({"accessory", "styling_piece", "day_to_night"})
    if "outerwear" in category_text or "jacket" in category_text or "coat" in category_text:
        traits.update({"outerwear", "layerable", "city_walking"})
    if "top" in category_text or "bottom" in category_text or "skirt" in category_text:
        traits.update({"separates", "versatile", "daywear"})
    return traits


def _infer_season(
    traits: set[str],
    explicit_season: str | None,
) -> tuple[str, list[str]]:
    if explicit_season:
        return _normalize_option(explicit_season) or "unspecified", []
    cool = {"cold_weather", "insulating", "heavyweight", "outerwear"}
    warm = {
        "warm_weather",
        "breathable",
        "airy",
        "resort",
        "coastal",
        "skin_exposure",
        "heat",
    }
    cool_count = len(cool & traits)
    warm_count = len(warm & traits)
    if cool_count > warm_count and cool_count:
        return "cool-season", ["cool-season use inferred from construction"]
    if warm_count:
        return "warm-season", ["warm-season use inferred from construction"]
    return "unspecified", ["season not supplied; confidence reduced"]


def _infer_occasion(
    evidence: FashionEvidence,
    traits: set[str],
    explicit_occasion: str | None,
) -> tuple[str, list[str]]:
    if explicit_occasion:
        return _normalize_option(explicit_occasion) or "unspecified", []
    occasion_concepts = [
        item.concept_id
        for item in evidence.concepts
        if item.category == "occasion"
    ]
    if occasion_concepts:
        return occasion_concepts[0].replace("_", "-"), [
            "occasion inferred from product evidence"
        ]
    if "evening" in traits or "glamorous" in traits:
        return "evening", ["evening use inferred from styling"]
    if "resort" in traits or "vacation" in traits:
        return "resort", ["resort use inferred from styling"]
    if "daywear" in traits or "casual" in traits:
        return "daytime", ["daytime use inferred from garment category"]
    return "unspecified", ["occasion not supplied; confidence reduced"]


def _trait_matches(
    traits: set[str],
    weights: dict[str, float] | None,
) -> list[tuple[str, Decimal]]:
    return sorted(
        [
            (trait, Decimal(str(weight)))
            for trait, weight in (weights or {}).items()
            if trait in traits
        ],
        key=lambda item: (-item[1], item[0]),
    )


def _trait_reason(
    matched: list[tuple[str, Decimal]],
    evidence: FashionEvidence,
    *,
    prefix: str,
) -> str | None:
    labels: list[str] = []
    for trait, _weight in matched:
        trait_labels = evidence.trait_evidence.get(trait)
        labels.append((trait_labels or (trait.replace("_", " "),))[0])
    labels = list(dict.fromkeys(labels))
    if not labels:
        return None
    return f"{prefix}: " + ", ".join(labels[:5])


@dataclass(frozen=True)
class ConnectionContext:
    component_bonus: Decimal
    distinctive_bonus: Decimal
    reasons: list[str]
    connection_type: str | None
    connection_note: str | None
    merchant_profile_key: str | None


def _connection_context(
    *,
    destination_slug: str,
    evidence: FashionEvidence,
    merchant_name: str | None,
    merchant_profile_allowed: bool,
) -> ConnectionContext:
    component_bonus = Decimal("0")
    distinctive_bonus = Decimal("0")
    reasons: list[str] = []
    connection_type: str | None = None
    connection_note: str | None = None
    merchant_profile_key: str | None = None

    brand = evidence.brand
    if brand is not None and brand.origin == destination_slug:
        strength = Decimal(str(brand.strength))
        component_bonus += Decimal("0.45") * strength
        distinctive_bonus += Decimal("1.30") * strength
        reasons.append(f"{brand.key.replace('-', ' ').title()} has a native destination connection")
        connection_type = "city_based_brand"
        connection_note = f"Recognized brand origin: {destination_slug.replace('-', ' ')}"
    elif brand is not None and destination_slug in brand.affinities:
        affinity = Decimal(str(brand.affinities[destination_slug]))
        component_bonus += affinity * Decimal("0.35")
        distinctive_bonus += affinity * Decimal("0.65")
        reasons.append(f"{brand.key.replace('-', ' ').title()} has established destination affinity")
        connection_type = "city_compatible_brand"
        connection_note = f"Recognized brand affinity: {destination_slug.replace('-', ' ')}"

    merchant_profile = (
        get_merchant_profile(merchant_name)
        if merchant_profile_allowed
        else None
    )
    if merchant_profile is not None:
        merchant_profile_key = merchant_profile.merchant_key
        if merchant_profile.origin_city_slug == destination_slug:
            component_bonus += Decimal("0.18")
            distinctive_bonus += Decimal("0.45")
            reasons.append("verified merchant origin supports the destination")
            connection_type = connection_type or "city_based_brand"
        elif destination_slug in merchant_profile.best_city_slugs:
            component_bonus += Decimal("0.10")
            distinctive_bonus += Decimal("0.22")
        elif destination_slug in merchant_profile.compatible_city_slugs:
            component_bonus += Decimal("0.05")
            distinctive_bonus += Decimal("0.10")
        elif destination_slug in merchant_profile.weaker_city_slugs:
            component_bonus -= Decimal("0.08")
        connection_type = connection_type or merchant_profile.source_type
        connection_note = connection_note or merchant_profile.aspiration

    return ConnectionContext(
        component_bonus=component_bonus,
        distinctive_bonus=distinctive_bonus,
        reasons=reasons,
        connection_type=connection_type,
        connection_note=connection_note,
        merchant_profile_key=merchant_profile_key,
    )


def _visual_component(
    *,
    traits: set[str],
    evidence: FashionEvidence,
    profile: dict[str, object],
    connection: ConnectionContext,
    component_weights: dict[str, Decimal] | None = None,
) -> tuple[ComponentScore, list[tuple[str, Decimal]], list[tuple[str, Decimal]]]:
    positive = _trait_matches(traits, profile.get("visual_traits"))
    conflicts = _trait_matches(traits, profile.get("visual_conflicts"))
    top_positive = positive[:5]
    raw = Decimal("6.4")
    raw += min(
        sum((weight for _trait, weight in top_positive[:4]), Decimal("0"))
        * Decimal("0.34"),
        Decimal("2.7"),
    )
    raw += Decimal(str(min(len(top_positive), 4))) * Decimal("0.08")
    raw -= min(
        sum((weight for _trait, weight in conflicts[:3]), Decimal("0"))
        * Decimal("0.45"),
        Decimal("2.3"),
    )
    raw += connection.component_bonus

    reasons: list[str] = []
    positive_reason = _trait_reason(
        top_positive,
        evidence,
        prefix="recognized aesthetic",
    )
    conflict_reason = _trait_reason(
        conflicts,
        evidence,
        prefix="documented aesthetic conflict",
    )
    if positive_reason:
        reasons.append(positive_reason)
    else:
        reasons.append("no distinctive aesthetic signal; neutral baseline retained")
    if conflict_reason:
        reasons.append(conflict_reason)
    if connection.reasons:
        reasons.append(connection.reasons[0])
    return (
        _component(
            "visual_aesthetic",
            raw,
            reasons,
            component_weights=component_weights,
        ),
        positive,
        conflicts,
    )


def _climate_component(
    *,
    traits: set[str],
    concept_ids: frozenset[str],
    climate: str,
    season: str,
    material_confirmed: bool,
    component_weights: dict[str, Decimal] | None = None,
) -> ComponentScore:
    raw = {
        "warm-dry": Decimal("7.0"),
        "warm-humid": Decimal("6.8"),
        "temperate-coastal": Decimal("7.1"),
        "mild-variable": Decimal("7.0"),
        "four-season-humid": Decimal("6.9"),
    }[climate]
    breathable = bool({"breathable", "natural_fiber", "airy", "lightweight"} & traits)
    flowing = bool({"flowing", "movement", "drape", "relaxed"} & traits)
    layerable = "layerable" in traits or "outerwear" in traits
    exposure = bool({"skin_exposure", "open", "cutout", "strapless", "sleeveless", "mini"} & traits)
    heavy = bool({"cold_weather", "insulating", "heavyweight", "shearling"} & traits)
    humidity_risk = bool(
        {"polyester", "acrylic", "faux_leather", "neoprene", "velvet"}
        & set(concept_ids)
    )
    reasons = [f"evaluated for {season.replace('-', ' ')} in a {climate.replace('-', ' ')} destination"]

    if climate == "warm-dry":
        raw += Decimal("0.55") if breathable else Decimal("0")
        raw += Decimal("0.40") if flowing else Decimal("0")
        raw += Decimal("0.25") if exposure else Decimal("0")
        raw -= Decimal("1.5") if heavy else Decimal("0")
    elif climate == "warm-humid":
        raw += Decimal("0.70") if breathable else Decimal("0")
        raw += Decimal("0.35") if flowing else Decimal("0")
        raw += Decimal("0.20") if exposure else Decimal("0")
        raw -= Decimal("0.85") if humidity_risk else Decimal("0")
        raw -= Decimal("1.6") if heavy else Decimal("0")
    elif climate == "temperate-coastal":
        raw += Decimal("0.35") if breathable else Decimal("0")
        raw += Decimal("0.40") if flowing else Decimal("0")
        raw += Decimal("0.40") if layerable else Decimal("0")
        raw -= Decimal("0.65") if heavy and season != "cool-season" else Decimal("0")
    elif climate == "mild-variable":
        raw += Decimal("0.60") if layerable else Decimal("0")
        raw += Decimal("0.30") if breathable else Decimal("0")
        raw -= Decimal("0.30") if exposure and season != "cool-season" else Decimal("0")
        raw -= Decimal("0.80") if exposure and season == "cool-season" else Decimal("0")
        raw += Decimal("0.45") if heavy and season == "cool-season" else Decimal("0")
    else:
        raw += Decimal("0.50") if breathable and season != "cool-season" else Decimal("0")
        raw += Decimal("0.35") if layerable else Decimal("0")
        raw -= Decimal("0.70") if humidity_risk and season != "cool-season" else Decimal("0")
        raw -= Decimal("0.80") if heavy and season != "cool-season" else Decimal("0")
        raw += Decimal("0.45") if heavy and season == "cool-season" else Decimal("0")

    if breathable:
        reasons.append("breathable or natural-fiber evidence confirmed")
    if flowing:
        reasons.append("movement supports comfort and practical wear")
    if layerable:
        reasons.append("layering flexibility supports variable weather")
    if humidity_risk:
        reasons.append("confirmed material may retain heat or moisture")
    if heavy and climate in {"warm-dry", "warm-humid"}:
        reasons.append("confirmed weight conflicts with warm conditions")
    if not material_confirmed:
        raw = min(raw, Decimal("8.0"))
        reasons.append("material not confirmed; confidence reduced and high score capped")
    return _component(
        "climate_practicality",
        raw,
        reasons,
        component_weights=component_weights,
    )


def _lifestyle_component(
    *,
    traits: set[str],
    evidence: FashionEvidence,
    profile: dict[str, object],
    occasion: str,
    normalized_category: str | None,
    component_weights: dict[str, Decimal] | None = None,
) -> tuple[ComponentScore, list[tuple[str, Decimal]]]:
    positive = _trait_matches(traits, profile.get("lifestyle_traits"))
    raw = Decimal("6.6") if normalized_category else Decimal("6.3")
    if any(item.category == "garment_type" for item in evidence.concepts):
        raw += Decimal("0.25")
    raw += min(
        sum((weight for _trait, weight in positive[:4]), Decimal("0"))
        * Decimal("0.30"),
        Decimal("2.25"),
    )
    if occasion != "unspecified" and positive:
        raw += Decimal("0.15")
    reasons: list[str] = []
    positive_reason = _trait_reason(
        positive,
        evidence,
        prefix="natural lifestyle use",
    )
    if positive_reason:
        reasons.append(positive_reason)
    else:
        reasons.append("broad category utility retained without inventing an occasion")
    if occasion != "unspecified":
        reasons.append(f"evaluated for {occasion.replace('-', ' ')} use")
    return (
        _component(
            "lifestyle_occasion",
            raw,
            reasons,
            component_weights=component_weights,
        ),
        positive,
    )


def _distinctive_component(
    *,
    visual_positive: list[tuple[str, Decimal]],
    visual_conflicts: list[tuple[str, Decimal]],
    connection: ConnectionContext,
    component_weights: dict[str, Decimal] | None = None,
) -> ComponentScore:
    raw = Decimal("6.0")
    raw += min(
        sum((weight for _trait, weight in visual_positive[:3]), Decimal("0"))
        * Decimal("0.38"),
        Decimal("2.35"),
    )
    if len(visual_positive) >= 3:
        raw += Decimal("0.30")
    raw -= min(
        sum((weight for _trait, weight in visual_conflicts[:3]), Decimal("0"))
        * Decimal("0.42"),
        Decimal("2.0"),
    )
    raw += connection.distinctive_bonus
    if not visual_positive and not connection.reasons:
        raw = min(raw, Decimal("6.3"))
    elif len(visual_positive) == 1 and not connection.reasons:
        raw = min(raw, Decimal("7.5"))

    reasons: list[str] = []
    if visual_positive:
        reasons.append(
            f"{len(visual_positive)} reinforcing destination relationships"
        )
    else:
        reasons.append("destination does not uniquely enhance the garment")
    reasons.extend(connection.reasons[:2])
    return _component(
        "distinctive_enhancement",
        raw,
        reasons,
        component_weights=component_weights,
    )


def _specific_evidence_items(
    text: str | None,
    *,
    source: str,
    marketing_copy: bool,
    concept_overrides: tuple[dict[str, Any], ...],
) -> tuple[GarmentEvidenceItem, ...]:
    if not text or not text.strip():
        return ()
    evidence = recognize_fashion_evidence(
        text,
        concept_overrides=concept_overrides,
    )
    return tuple(
        GarmentEvidenceItem(
            detail=concept.label,
            source=source,
            category=concept.category,
            traits=concept.traits,
            marketing_copy=marketing_copy,
        )
        for concept in evidence.concepts
        if concept.category in STRICT_SPECIFIC_EVIDENCE_CATEGORIES
    )


def _extract_garment_facts(
    *,
    title: str,
    description: str | None,
    tags: list[str] | None,
    manual_observed_garment_details: Iterable[str],
    image_observed_garment_details: Iterable[str],
    concept_overrides: tuple[dict[str, Any], ...],
) -> tuple[GarmentEvidenceItem, ...]:
    """Extract concrete garment facts before any destination is considered."""
    items: list[GarmentEvidenceItem] = []
    items.extend(
        _specific_evidence_items(
            title,
            source="product_title",
            marketing_copy=True,
            concept_overrides=concept_overrides,
        )
    )
    items.extend(
        _specific_evidence_items(
            description,
            source="product_description",
            marketing_copy=True,
            concept_overrides=concept_overrides,
        )
    )
    items.extend(
        _specific_evidence_items(
            " ".join(tags or []),
            source="product_tags",
            marketing_copy=True,
            concept_overrides=concept_overrides,
        )
    )
    for detail in manual_observed_garment_details:
        items.extend(
            _specific_evidence_items(
                detail,
                source="manual_curator_observation",
                marketing_copy=False,
                concept_overrides=concept_overrides,
            )
        )
    for detail in image_observed_garment_details:
        items.extend(
            _specific_evidence_items(
                detail,
                source="product_image",
                marketing_copy=False,
                concept_overrides=concept_overrides,
            )
        )

    deduplicated: dict[tuple[str, str, str], GarmentEvidenceItem] = {}
    for item in items:
        key = (item.detail.lower(), item.source, item.category)
        deduplicated.setdefault(key, item)
    return tuple(deduplicated.values())


def _strict_specificity_score(items: tuple[GarmentEvidenceItem, ...]) -> int:
    unique_details = {item.detail.lower() for item in items}
    unique_categories = {item.category for item in items}
    non_marketing_sources = {
        item.source for item in items if item.source in NON_MARKETING_EVIDENCE_SOURCES
    }
    score = min(len(unique_details) * 2, 6)
    score += min(max(len(unique_categories) - 1, 0), 1)
    score += 1 if non_marketing_sources else 0
    return min(score, 8)


def _strict_alignment_score(
    items: tuple[GarmentEvidenceItem, ...],
    profile: dict[str, object],
) -> tuple[int, tuple[str, ...], tuple[GarmentEvidenceItem, ...]]:
    marker_weights: dict[str, Decimal] = {}
    for marker_group in ("visual_traits", "lifestyle_traits"):
        for trait, raw_weight in (profile.get(marker_group) or {}).items():
            weight = Decimal(str(raw_weight))
            marker_weights[trait] = max(marker_weights.get(trait, Decimal("0")), weight)

    matched_traits: dict[str, Decimal] = {}
    supporting_items: list[GarmentEvidenceItem] = []
    for item in items:
        item_matched = False
        for trait in item.traits:
            weight = marker_weights.get(trait)
            if weight is None:
                continue
            matched_traits[trait] = max(
                matched_traits.get(trait, Decimal("0")),
                weight,
            )
            item_matched = True
        if item_matched:
            supporting_items.append(item)

    raw = sum(matched_traits.values(), Decimal("0")) * Decimal("1.35")
    raw += Decimal(str(min(len(matched_traits), 4))) * Decimal("0.35")
    points = int(
        min(Decimal("9"), raw).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    deduplicated_support = tuple(
        {
            (item.detail.lower(), item.source): item
            for item in supporting_items
        }.values()
    )
    return points, tuple(sorted(matched_traits)), deduplicated_support


@dataclass(frozen=True)
class StrictDestinationBase:
    destination_slug: str
    profile: dict[str, object]
    connection: ConnectionContext
    visual: ComponentScore
    climate: ComponentScore
    lifestyle: ComponentScore
    general_points: Decimal
    city_fit_percentage: int
    alignment_score: int
    alignment_traits: tuple[str, ...]
    supporting_evidence: tuple[GarmentEvidenceItem, ...]
    confidence: int
    evidence_gaps: tuple[str, ...]


def _strict_destination_base(
    *,
    destination_slug: str,
    profile: dict[str, object],
    evidence: FashionEvidence,
    garment_facts: tuple[GarmentEvidenceItem, ...],
    traits: set[str],
    description_supplied: bool,
    normalized_category: str | None,
    season: str,
    occasion: str,
    merchant_name: str | None,
    merchant_profile_allowed: bool,
) -> StrictDestinationBase:
    connection = _connection_context(
        destination_slug=destination_slug,
        evidence=evidence,
        merchant_name=merchant_name,
        merchant_profile_allowed=merchant_profile_allowed,
    )
    # Source authenticity remains visible metadata, but strict garment scoring
    # cannot gain component points from a brand or merchant name.
    garment_only_connection = ConnectionContext(
        component_bonus=Decimal("0"),
        distinctive_bonus=Decimal("0"),
        reasons=[],
        connection_type=connection.connection_type,
        connection_note=connection.connection_note,
        merchant_profile_key=connection.merchant_profile_key,
    )
    visual, _visual_positive, visual_conflicts = _visual_component(
        traits=traits,
        evidence=evidence,
        profile=profile,
        connection=garment_only_connection,
        component_weights=STRICT_COMPONENT_WEIGHTS,
    )
    climate = _climate_component(
        traits=traits,
        concept_ids=evidence.concept_ids,
        climate=str(profile["climate"]),
        season=season,
        material_confirmed=evidence.material_confirmed,
        component_weights=STRICT_COMPONENT_WEIGHTS,
    )
    lifestyle, _lifestyle_positive = _lifestyle_component(
        traits=traits,
        evidence=evidence,
        profile=profile,
        occasion=occasion,
        normalized_category=normalized_category,
        component_weights=STRICT_COMPONENT_WEIGHTS,
    )
    general_points = sum(
        (
            visual.weighted_points,
            climate.weighted_points,
            lifestyle.weighted_points,
        ),
        Decimal("0"),
    )
    city_fit_percentage = int(
        (general_points / Decimal("75") * Decimal("100")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
    alignment_score, alignment_traits, supporting_evidence = (
        _strict_alignment_score(garment_facts, profile)
    )

    evidence_gaps: list[str] = []
    if not evidence.material_confirmed:
        evidence_gaps.append("Material not confirmed")
    if season == "unspecified":
        evidence_gaps.append("Season not supplied")
    if occasion == "unspecified":
        evidence_gaps.append("Occasion not supplied")
    if not description_supplied:
        evidence_gaps.append("Detailed product description unavailable")
    if not garment_facts:
        evidence_gaps.append("No specific garment detail recorded")

    confidence = 35
    confidence += 15 if description_supplied else 0
    confidence += 15 if evidence.material_confirmed else 0
    confidence += min(len(evidence.concepts), 8) * 4
    confidence += 6 if season != "unspecified" else 0
    confidence += 6 if occasion != "unspecified" else 0
    confidence += 4 if visual_conflicts else 0
    confidence = min(100, confidence)
    if not evidence.material_confirmed:
        confidence = min(confidence, 75)

    return StrictDestinationBase(
        destination_slug=destination_slug,
        profile=profile,
        connection=connection,
        visual=visual,
        climate=climate,
        lifestyle=lifestyle,
        general_points=general_points,
        city_fit_percentage=max(0, min(100, city_fit_percentage)),
        alignment_score=alignment_score,
        alignment_traits=alignment_traits,
        supporting_evidence=supporting_evidence,
        confidence=confidence,
        evidence_gaps=tuple(evidence_gaps),
    )


def _comparative_separation_points(
    primary: StrictDestinationBase,
    rival: StrictDestinationBase,
) -> int:
    fit_delta = primary.city_fit_percentage - rival.city_fit_percentage
    alignment_delta = primary.alignment_score - rival.alignment_score
    if fit_delta <= 0 and alignment_delta <= 0:
        return 0
    if fit_delta <= 3 and alignment_delta <= 1:
        return 0

    signal = max(fit_delta, 0) + max(alignment_delta, 0) * 3
    if signal <= 4:
        return 1
    if signal <= 8:
        return 2
    if signal <= 12:
        return 4
    if signal <= 18:
        return 6
    return 8


def evaluate_primary_match_gate(
    *,
    raw_total: int,
    distinctiveness_score: int,
    observed_garment_details: Iterable[str],
    nearest_rival_test_passed: bool,
    marketing_language_primary: bool,
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if raw_total < HAROONA_SELECTION_THRESHOLD:
        failures.append("raw_total_below_threshold")
    if distinctiveness_score < 10:
        failures.append("distinctiveness_below_minimum")
    if not any(str(item).strip() for item in observed_garment_details):
        failures.append("observed_evidence_missing")
    if not nearest_rival_test_passed:
        failures.append("nearest_rival_test_failed")
    if marketing_language_primary:
        failures.append("marketing_language_primary")
    return not failures, tuple(failures)


def _strict_match_type(
    *,
    primary_match_eligible: bool,
    distinctiveness_score: int,
    city_fit_percentage: int,
    rival_city_fit_percentage: int,
) -> str:
    if primary_match_eligible:
        return "distinctive_primary_match"
    if (
        city_fit_percentage >= 80
        and abs(city_fit_percentage - rival_city_fit_percentage) <= 3
    ):
        return "strong_multi_city_fit"
    if distinctiveness_score >= 10:
        return "city_leaning"
    return "broad_match"


def _comparative_reason(
    primary: StrictDestinationBase,
    rival: StrictDestinationBase,
    *,
    separation_points: int,
) -> str:
    primary_name = str(primary.profile["display_name"])
    rival_name = str(rival.profile["display_name"])
    supporting_details = list(
        dict.fromkeys(item.detail for item in primary.supporting_evidence)
    )
    if supporting_details:
        support = ", ".join(supporting_details[:3])
        first_clause = f"the recorded details ({support}) align with its style markers"
    else:
        first_clause = (
            "its visual, climate, and lifestyle fit is broad, without a "
            "city-specific observed marker"
        )

    if separation_points >= 2:
        second_clause = (
            f"the same details have weaker marker alignment for {rival_name}"
        )
    elif abs(primary.city_fit_percentage - rival.city_fit_percentage) <= 3:
        second_clause = (
            "the two cities remain in the same general-fit tier and the recorded "
            "details do not clearly separate them"
        )
    else:
        second_clause = (
            f"{rival_name} has equal or stronger support, so the swap test does "
            "not establish a primary city"
        )
    return (
        f"This garment fits {primary_name} because {first_clause}, while "
        f"{rival_name} receives less support because {second_clause}."
    )


def _strict_destination_details(
    *,
    profiles: dict[str, dict[str, Any]],
    evidence: FashionEvidence,
    garment_facts: tuple[GarmentEvidenceItem, ...],
    traits: set[str],
    description_supplied: bool,
    normalized_category: str | None,
    season: str,
    occasion: str,
    assumptions: list[str],
    merchant_name: str | None,
    merchant_profile_allowed: bool,
) -> dict[str, CityScoreDetail]:
    specificity_score = _strict_specificity_score(garment_facts)
    observed_details = tuple(
        dict.fromkeys(item.detail for item in garment_facts)
    )
    destination_slugs = tuple(profiles)

    def build_base(destination_slug: str) -> StrictDestinationBase:
        return _strict_destination_base(
            destination_slug=destination_slug,
            profile=profiles[destination_slug],
            evidence=evidence,
            garment_facts=garment_facts,
            traits=traits,
            description_supplied=description_supplied,
            normalized_category=normalized_category,
            season=season,
            occasion=occasion,
            merchant_name=merchant_name,
            merchant_profile_allowed=merchant_profile_allowed,
        )

    if len(destination_slugs) > 1:
        with ThreadPoolExecutor(
            max_workers=min(4, len(destination_slugs)),
            thread_name_prefix="haroona-city-score",
        ) as executor:
            bases = dict(zip(destination_slugs, executor.map(build_base, destination_slugs)))
    else:
        bases = {
            destination_slug: build_base(destination_slug)
            for destination_slug in destination_slugs
        }

    details: dict[str, CityScoreDetail] = {}
    for destination_slug, base in bases.items():
        rivals = [item for slug, item in bases.items() if slug != destination_slug]
        rival = (
            sorted(
                rivals,
                key=lambda item: (
                    -item.city_fit_percentage,
                    -item.alignment_score,
                    item.destination_slug,
                ),
            )[0]
            if rivals
            else base
        )
        separation_score = (
            _comparative_separation_points(base, rival) if rivals else 8
        )
        distinctiveness_score = min(
            25,
            specificity_score + base.alignment_score + separation_score,
        )
        raw_total = int(
            (base.general_points + Decimal(distinctiveness_score)).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        supportive_evidence = tuple(
            item.as_dict() for item in base.supporting_evidence
        )
        marketing_language_primary = not any(
            item.source in NON_MARKETING_EVIDENCE_SOURCES
            for item in base.supporting_evidence
        )
        nearest_rival_test_passed = separation_score >= 2
        primary_match_eligible, gate_failures = evaluate_primary_match_gate(
            raw_total=raw_total,
            distinctiveness_score=distinctiveness_score,
            observed_garment_details=observed_details,
            nearest_rival_test_passed=nearest_rival_test_passed,
            marketing_language_primary=marketing_language_primary,
        )
        match_type = _strict_match_type(
            primary_match_eligible=primary_match_eligible,
            distinctiveness_score=distinctiveness_score,
            city_fit_percentage=base.city_fit_percentage,
            rival_city_fit_percentage=rival.city_fit_percentage,
        )
        comparison = (
            _comparative_reason(
                base,
                rival,
                separation_points=separation_score,
            )
            if rivals
            else "This is the only active Haroona city available for comparison."
        )
        breakdown = {
            "observed_marker_specificity": specificity_score,
            "city_marker_alignment": base.alignment_score,
            "comparative_separation": separation_score,
        }
        component_points = {
            "visual_aesthetic": float(base.visual.weighted_points),
            "climate_practicality": float(base.climate.weighted_points),
            "lifestyle_occasion": float(base.lifestyle.weighted_points),
            "distinctive_enhancement": float(distinctiveness_score),
        }
        component_scores = {
            "visual_aesthetic": float(base.visual.score),
            "climate_practicality": float(base.climate.score),
            "lifestyle_occasion": float(base.lifestyle.score),
            "distinctive_enhancement": float(
                _one_decimal(
                    Decimal(distinctiveness_score)
                    / STRICT_COMPONENT_WEIGHTS["distinctive_enhancement"]
                    * Decimal("10")
                )
            ),
        }
        component_reasons = {
            "visual_aesthetic": base.visual.reasons,
            "climate_practicality": base.climate.reasons,
            "lifestyle_occasion": base.lifestyle.reasons,
            "distinctive_enhancement": [
                f"Observed marker specificity {specificity_score}/8",
                f"City-marker alignment {base.alignment_score}/9",
                f"Comparative separation {separation_score}/8",
            ],
        }
        display_match_type = match_type.replace("_", " ").title()
        reasons = [
            (
                f"Visual compatibility {base.visual.score}/10 "
                f"({base.visual.weighted_points}/30)"
            ),
            (
                f"Climate compatibility {base.climate.score}/10 "
                f"({base.climate.weighted_points}/25)"
            ),
            (
                f"Lifestyle compatibility {base.lifestyle.score}/10 "
                f"({base.lifestyle.weighted_points}/20)"
            ),
            f"Distinctiveness {distinctiveness_score}/25",
            f"Raw total {raw_total}/100",
            f"City Fit {base.city_fit_percentage}%",
            f"Classification: {display_match_type}",
            comparison,
        ]
        if gate_failures:
            reasons.append(
                "Primary Match advisory: "
                + ", ".join(reason.replace("_", " ") for reason in gate_failures)
            )

        details[destination_slug] = CityScoreDetail(
            score=max(0, min(100, raw_total)),
            reasons=reasons[:14],
            confidence=base.confidence,
            component_scores=component_scores,
            component_points=component_points,
            component_reasons=component_reasons,
            tier=display_match_type,
            is_haroona_selection=primary_match_eligible,
            assumptions=list(assumptions),
            evidence_gaps=list(base.evidence_gaps),
            display_name=str(base.profile["display_name"]),
            destination_type=str(base.profile["destination_type"]),
            city_connection_type=base.connection.connection_type,
            city_connection_note=base.connection.connection_note,
            merchant_profile_key=base.connection.merchant_profile_key,
            recognized_concepts=tuple(item.label for item in evidence.concepts[:20]),
            scoring_mode=STRICT_DISTINCTIVENESS_SCORING_MODE,
            scoring_version=STRICT_DISTINCTIVENESS_SCORING_VERSION,
            raw_total=max(0, min(100, raw_total)),
            city_fit_percentage=base.city_fit_percentage,
            distinctiveness_score=distinctiveness_score,
            distinctiveness_breakdown=breakdown,
            primary_match_eligible=primary_match_eligible,
            match_type=match_type,
            gate_failure_reasons=gate_failures,
            observed_garment_details=observed_details,
            distinctiveness_evidence=supportive_evidence,
            nearest_competing_city=(
                rival.destination_slug if rivals else None
            ),
            nearest_rival_test_passed=nearest_rival_test_passed,
            comparative_reason=comparison,
            marketing_language_primary=marketing_language_primary,
        )
    return details


def _score_one_destination(
    *,
    destination_slug: str,
    profile: dict[str, object],
    evidence: FashionEvidence,
    traits: set[str],
    description_supplied: bool,
    normalized_category: str | None,
    season: str,
    occasion: str,
    assumptions: list[str],
    merchant_name: str | None,
    merchant_profile_allowed: bool,
) -> CityScoreDetail:
    connection = _connection_context(
        destination_slug=destination_slug,
        evidence=evidence,
        merchant_name=merchant_name,
        merchant_profile_allowed=merchant_profile_allowed,
    )
    visual, visual_positive, visual_conflicts = _visual_component(
        traits=traits,
        evidence=evidence,
        profile=profile,
        connection=connection,
    )
    climate = _climate_component(
        traits=traits,
        concept_ids=evidence.concept_ids,
        climate=str(profile["climate"]),
        season=season,
        material_confirmed=evidence.material_confirmed,
    )
    lifestyle, lifestyle_positive = _lifestyle_component(
        traits=traits,
        evidence=evidence,
        profile=profile,
        occasion=occasion,
        normalized_category=normalized_category,
    )
    distinctive = _distinctive_component(
        visual_positive=visual_positive,
        visual_conflicts=visual_conflicts,
        connection=connection,
    )
    components = {
        "visual_aesthetic": visual,
        "climate_practicality": climate,
        "lifestyle_occasion": lifestyle,
        "distinctive_enhancement": distinctive,
    }
    exact_total = sum(
        (item.weighted_points for item in components.values()),
        Decimal("0"),
    )
    score = int(exact_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    evidence_gaps: list[str] = []
    if not evidence.material_confirmed:
        evidence_gaps.append("Material not confirmed")
    if season == "unspecified":
        evidence_gaps.append("Season not supplied")
    if occasion == "unspecified":
        evidence_gaps.append("Occasion not supplied")
    if not description_supplied:
        evidence_gaps.append("Detailed product description unavailable")

    confidence = 35
    confidence += 15 if description_supplied else 0
    confidence += 15 if evidence.material_confirmed else 0
    confidence += min(len(evidence.concepts), 8) * 4
    confidence += 8 if evidence.brand is not None else 0
    confidence += 6 if season != "unspecified" else 0
    confidence += 6 if occasion != "unspecified" else 0
    confidence += 4 if visual_conflicts else 0
    confidence = min(100, confidence)
    if not evidence.material_confirmed:
        confidence = min(confidence, 75)

    component_scores = {
        key: float(item.score)
        for key, item in components.items()
    }
    component_points = {
        key: float(item.weighted_points)
        for key, item in components.items()
    }
    component_reasons = {
        key: item.reasons
        for key, item in components.items()
    }
    reasons = [
        f"Visual silhouette & aesthetic {visual.score}/10 ({visual.weighted_points}/35)",
        f"Climate, material & practicality {climate.score}/10 ({climate.weighted_points}/30)",
        f"Lifestyle & occasion alignment {lifestyle.score}/10 ({lifestyle.weighted_points}/20)",
        f"Distinctive destination enhancement {distinctive.score}/10 ({distinctive.weighted_points}/15)",
        f"Verdict: {_score_tier(score)}",
    ]
    for item in components.values():
        reasons.extend(item.reasons[:1])
    if evidence_gaps:
        reasons.append("Evidence gaps: " + ", ".join(evidence_gaps))

    return CityScoreDetail(
        score=max(0, min(100, score)),
        reasons=reasons[:14],
        confidence=confidence,
        component_scores=component_scores,
        component_points=component_points,
        component_reasons=component_reasons,
        tier=_score_tier(score),
        is_haroona_selection=score >= HAROONA_SELECTION_THRESHOLD,
        assumptions=list(assumptions),
        evidence_gaps=evidence_gaps,
        display_name=str(profile["display_name"]),
        destination_type=str(profile["destination_type"]),
        city_connection_type=connection.connection_type,
        city_connection_note=connection.connection_note,
        merchant_profile_key=connection.merchant_profile_key,
        recognized_concepts=tuple(item.label for item in evidence.concepts[:20]),
        scoring_mode=LEGACY_SCORING_MODE,
        scoring_version=HYBRID_SCORING_VERSION,
        raw_total=max(0, min(100, score)),
        city_fit_percentage=max(0, min(100, score)),
        distinctiveness_score=int(
            distinctive.weighted_points.quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        ),
        match_type=(
            "legacy_haroona_selection"
            if score >= HAROONA_SELECTION_THRESHOLD
            else "legacy_city_fit"
        ),
    )


def score_city_fit(
    *,
    title: str,
    description: str | None = None,
    product_type: str | None = None,
    tags: list[str] | None = None,
    target_city_slug: str | None = "london",
    normalized_category: str | None = None,
    merchant_name: str | None = None,
    merchant_profile_allowed: bool = True,
    brand_name: str | None = None,
    season: str | None = None,
    occasion: str | None = None,
    concept_overrides: tuple[dict[str, Any], ...] = (),
    scoring_mode: str = LEGACY_SCORING_MODE,
    manual_observed_garment_details: Iterable[str] = (),
    image_observed_garment_details: Iterable[str] = (),
    candidate_city_slugs: Iterable[str] | None = None,
) -> ScoreResult:
    """Apply Haroona's deterministic, JSON-backed hybrid rubric.

    Missing evidence lowers confidence rather than being treated as a mismatch.
    Only confirmed positive relationships and confirmed conflicts change the
    neutral fit baseline.
    """
    active_mode = normalize_scoring_mode(scoring_mode)
    garment_facts = _extract_garment_facts(
        title=title,
        description=description,
        tags=tags,
        manual_observed_garment_details=manual_observed_garment_details,
        image_observed_garment_details=image_observed_garment_details,
        concept_overrides=concept_overrides,
    )
    combined_text = " ".join(
        [
            title or "",
            description or "",
            product_type or "",
            " ".join(tags or []),
            normalized_category or "",
            brand_name or "",
        ]
    )
    evidence = recognize_fashion_evidence(
        combined_text,
        brand_name=brand_name,
        concept_overrides=concept_overrides,
    )
    traits = _inferred_traits(
        evidence,
        normalized_category=normalized_category,
        product_type=product_type,
    )
    inferred_season, season_assumptions = _infer_season(traits, season)
    inferred_occasion, occasion_assumptions = _infer_occasion(
        evidence,
        traits,
        occasion,
    )
    assumptions = [*season_assumptions, *occasion_assumptions]
    all_profiles = destination_profiles()
    canonical_target = (
        DESTINATION_ALIASES.get(target_city_slug, target_city_slug)
        if target_city_slug
        else None
    )
    if candidate_city_slugs is None:
        profiles = all_profiles
    else:
        requested_city_slugs = tuple(
            dict.fromkeys(
                DESTINATION_ALIASES.get(str(slug).strip(), str(slug).strip())
                for slug in candidate_city_slugs
                if str(slug or "").strip()
            )
        )
        profiles = {
            slug: all_profiles[slug]
            for slug in requested_city_slugs
            if slug in all_profiles
        }
        if canonical_target in all_profiles and canonical_target not in profiles:
            profiles[canonical_target] = all_profiles[canonical_target]

    if canonical_target is not None and canonical_target not in all_profiles:
        scoring_version = SCORING_MODE_VERSIONS[active_mode]
        fallback = CityScoreDetail(
            score=45,
            reasons=["Destination profile unavailable", "Verdict: Weak"],
            confidence=10,
            component_scores={},
            component_points={},
            component_reasons={},
            tier="Weak",
            is_haroona_selection=False,
            assumptions=assumptions,
            evidence_gaps=["Destination profile unavailable"],
            display_name=target_city_slug.replace("-", " ").title(),
            destination_type="unknown",
            scoring_mode=active_mode,
            scoring_version=scoring_version,
            raw_total=45,
            city_fit_percentage=45,
            distinctiveness_score=0 if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE else None,
            distinctiveness_breakdown=(
                {
                    "observed_marker_specificity": _strict_specificity_score(
                        garment_facts
                    ),
                    "city_marker_alignment": 0,
                    "comparative_separation": 0,
                }
                if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE
                else None
            ),
            primary_match_eligible=(
                False
                if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE
                else None
            ),
            match_type=(
                "broad_match"
                if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE
                else "legacy_city_fit"
            ),
            gate_failure_reasons=(
                ("destination_profile_unavailable",)
                if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE
                else ()
            ),
            observed_garment_details=tuple(
                dict.fromkeys(item.detail for item in garment_facts)
            ),
        )
        return ScoreResult(
            score=fallback.score,
            reasons=fallback.reasons,
            city_fit_scores={target_city_slug: fallback.score},
            confidence=fallback.confidence,
            recommended_city_slug=target_city_slug,
            destination_details={target_city_slug: fallback},
            season=inferred_season,
            occasion=inferred_occasion,
            scoring_mode=active_mode,
            scoring_version=scoring_version,
            raw_total=fallback.raw_total,
            city_fit_percentage=fallback.city_fit_percentage,
            distinctiveness_score=fallback.distinctiveness_score,
            distinctiveness_breakdown=fallback.distinctiveness_breakdown,
            primary_match_eligible=fallback.primary_match_eligible,
            match_type=fallback.match_type,
            gate_failure_reasons=fallback.gate_failure_reasons,
            observed_garment_details=fallback.observed_garment_details,
            recognized_concepts=tuple(
                item.label for item in evidence.concepts[:20]
            ),
        )

    if not profiles:
        raise ValueError("No active Haroona cities have scoring profiles")

    if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE:
        details = _strict_destination_details(
            profiles=profiles,
            evidence=evidence,
            garment_facts=garment_facts,
            traits=traits,
            description_supplied=bool(description and description.strip()),
            normalized_category=normalized_category,
            season=inferred_season,
            occasion=inferred_occasion,
            assumptions=assumptions,
            merchant_name=merchant_name,
            merchant_profile_allowed=merchant_profile_allowed,
        )
    else:
        destination_slugs = tuple(profiles)

        def score_destination(destination_slug: str) -> CityScoreDetail:
            return _score_one_destination(
                destination_slug=destination_slug,
                profile=profiles[destination_slug],
                evidence=evidence,
                traits=traits,
                description_supplied=bool(description and description.strip()),
                normalized_category=normalized_category,
                season=inferred_season,
                occasion=inferred_occasion,
                assumptions=assumptions,
                merchant_name=merchant_name,
                merchant_profile_allowed=merchant_profile_allowed,
            )
        if len(destination_slugs) > 1:
            with ThreadPoolExecutor(
                max_workers=min(4, len(destination_slugs)),
                thread_name_prefix="haroona-city-score",
            ) as executor:
                details = dict(
                    zip(
                        destination_slugs,
                        executor.map(score_destination, destination_slugs),
                    )
                )
        else:
            details = {
                destination_slug: score_destination(destination_slug)
                for destination_slug in destination_slugs
            }

    ranked = sorted(details.items(), key=lambda item: (-item[1].score, item[0]))
    if canonical_target is None:
        canonical_target = ranked[0][0]
    target = details[canonical_target]
    alternatives = [item for item in ranked if item[0] != canonical_target]
    recommended_slug = ranked[0][0]
    if active_mode == STRICT_DISTINCTIVENESS_SCORING_MODE:
        city_fit_scores = {
            slug: detail.city_fit_percentage or 0
            for slug, detail in details.items()
        }
        secondary_city_slug = target.nearest_competing_city
    else:
        city_fit_scores = {
            slug: detail.score for slug, detail in details.items()
        }
        secondary_city_slug = alternatives[0][0] if alternatives else None

    return ScoreResult(
        score=target.score,
        reasons=target.reasons,
        city_connection_type=target.city_connection_type,
        city_connection_note=target.city_connection_note,
        merchant_profile_key=target.merchant_profile_key,
        city_fit_scores=city_fit_scores,
        secondary_city_slug=secondary_city_slug,
        confidence=target.confidence,
        recommended_city_slug=recommended_slug,
        destination_details=details,
        season=inferred_season,
        occasion=inferred_occasion,
        scoring_mode=active_mode,
        scoring_version=SCORING_MODE_VERSIONS[active_mode],
        raw_total=target.raw_total if target.raw_total is not None else target.score,
        city_fit_percentage=(
            target.city_fit_percentage
            if target.city_fit_percentage is not None
            else target.score
        ),
        distinctiveness_score=target.distinctiveness_score,
        distinctiveness_breakdown=target.distinctiveness_breakdown,
        primary_match_eligible=target.primary_match_eligible,
        match_type=target.match_type,
        gate_failure_reasons=target.gate_failure_reasons,
        observed_garment_details=target.observed_garment_details,
        distinctiveness_evidence=target.distinctiveness_evidence,
        nearest_competing_city=target.nearest_competing_city,
        nearest_rival_test_passed=target.nearest_rival_test_passed,
        comparative_reason=target.comparative_reason,
        marketing_language_primary=target.marketing_language_primary,
        recognized_concepts=target.recognized_concepts,
    )

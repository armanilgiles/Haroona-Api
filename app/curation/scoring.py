from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

from app.curation.fashion_ontology import (
    FashionEvidence,
    destination_profiles,
    load_fashion_ontology,
    recognize_fashion_evidence,
)
from app.curation.merchant_profiles import get_merchant_profile


HYBRID_SCORING_VERSION = str(load_fashion_ontology()["scoring_version"])
HAROONA_SELECTION_THRESHOLD = 80
HYBRID_COMPONENT_WEIGHTS: dict[str, Decimal] = {
    "visual_aesthetic": Decimal("35"),
    "climate_practicality": Decimal("30"),
    "lifestyle_occasion": Decimal("20"),
    "distinctive_enhancement": Decimal("15"),
}

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
    scoring_version: str = HYBRID_SCORING_VERSION


def _clamp(value: Decimal, lower: str = "1.0", upper: str = "10.0") -> Decimal:
    return max(Decimal(lower), min(Decimal(upper), value))


def _one_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _component(name: str, raw_score: Decimal, reasons: list[str]) -> ComponentScore:
    score = _one_decimal(_clamp(raw_score))
    weighted_points = _one_decimal(
        score * HYBRID_COMPONENT_WEIGHTS[name] / Decimal("10")
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
    return _component("visual_aesthetic", raw, reasons), positive, conflicts


def _climate_component(
    *,
    traits: set[str],
    concept_ids: frozenset[str],
    climate: str,
    season: str,
    material_confirmed: bool,
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
    return _component("climate_practicality", raw, reasons)


def _lifestyle_component(
    *,
    traits: set[str],
    evidence: FashionEvidence,
    profile: dict[str, object],
    occasion: str,
    normalized_category: str | None,
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
    return _component("lifestyle_occasion", raw, reasons), positive


def _distinctive_component(
    *,
    visual_positive: list[tuple[str, Decimal]],
    visual_conflicts: list[tuple[str, Decimal]],
    connection: ConnectionContext,
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
    return _component("distinctive_enhancement", raw, reasons)


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
    )


def score_city_fit(
    *,
    title: str,
    description: str | None = None,
    product_type: str | None = None,
    tags: list[str] | None = None,
    target_city_slug: str = "london",
    normalized_category: str | None = None,
    merchant_name: str | None = None,
    merchant_profile_allowed: bool = True,
    brand_name: str | None = None,
    season: str | None = None,
    occasion: str | None = None,
    concept_overrides: tuple[dict[str, Any], ...] = (),
) -> ScoreResult:
    """Apply Haroona's deterministic, JSON-backed hybrid rubric.

    Missing evidence lowers confidence rather than being treated as a mismatch.
    Only confirmed positive relationships and confirmed conflicts change the
    neutral fit baseline.
    """
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
    profiles = destination_profiles()
    canonical_target = DESTINATION_ALIASES.get(target_city_slug, target_city_slug)

    if canonical_target not in profiles:
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
        )

    details = {
        destination_slug: _score_one_destination(
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
        for destination_slug in SUPPORTED_CITY_SLUGS
    }
    target = details[canonical_target]
    ranked = sorted(details.items(), key=lambda item: (-item[1].score, item[0]))
    alternatives = [item for item in ranked if item[0] != canonical_target]
    recommended_slug = ranked[0][0]

    return ScoreResult(
        score=target.score,
        reasons=target.reasons,
        city_connection_type=target.city_connection_type,
        city_connection_note=target.city_connection_note,
        merchant_profile_key=target.merchant_profile_key,
        city_fit_scores={slug: detail.score for slug, detail in details.items()},
        secondary_city_slug=alternatives[0][0] if alternatives else None,
        confidence=target.confidence,
        recommended_city_slug=recommended_slug,
        destination_details=details,
        season=inferred_season,
        occasion=inferred_occasion,
    )

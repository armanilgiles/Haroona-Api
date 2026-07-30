from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.database import get_db
from app.models import (
    AwinProductNormalized,
    Brand,
    CatalogBrandControl,
    City,
    CurationScanRun,
    CurationScanRunCandidate,
    FashionConceptProposal,
    Merchant,
    MerchantCollection,
    Product,
    ProductCandidate,
)
from app.curation.concept_learning import (
    CONCEPT_CATEGORIES,
    create_concept_from_proposal,
    list_available_concepts,
    load_runtime_concept_overrides,
    map_proposal_to_concept,
    proposal_payload,
    record_unknown_concepts_for_scan,
    reject_concept_proposal,
)
from app.curation.candidate_queue import (
    CandidateTransitionError,
    apply_candidate_queue_filter,
    approve_candidate,
    archive_candidate,
    reject_candidate,
    resolve_candidate_queue_status,
    restore_candidate,
)
from app.curation.candidate_scoring import (
    assign_product_candidate_city,
    rescore_product_candidate,
)
from app.curation.city_assignment import (
    CITY_ASSIGNMENT_STATUSES,
    CityScanMode,
    active_scoring_city_slugs,
)
from app.curation.merchant_collections import (
    collection_payload,
    latest_scan_runs_by_collection,
    normalize_collection_url,
)
from app.curation.affiliate_links import (
    AffiliateLinkPersistenceError,
    AffiliateLinkPublicationError,
    AffiliateLinkTransitionError,
    affiliate_link_payload,
    invalidate_candidate_affiliate_link,
    resolve_candidate_workflow_status,
    resolve_takeads_affiliate_link,
    verify_candidate_affiliate_link,
)
from app.curation.product_candidate_publisher import (
    publish_approved_product_candidates,
    publish_product_candidate,
)
from app.curation.scanner_registry import UnsupportedScannerError, detect_curation_scanner
from app.curation.scan_observability import build_scan_observability
from app.curation.scoring_settings import (
    get_curation_scoring_configuration,
    set_curation_scoring_configuration,
)
from app.curation.scan_runs import (
    apply_scanned_candidate_filter,
    apply_scan_run_candidate_filter,
    apply_store_candidate_filter,
    complete_scan_run,
    fail_scan_run,
    list_scanned_stores,
    scan_run_payload,
    start_scan_run,
    update_scan_run_context,
)
from app.curation.shopify_collection import (
    CollectionDiscoveryError,
    CollectionRateLimitedError,
    CollectionScanOptions,
)
from app.curation.single_product import (
    NotProductPageError,
    ProductPageFetchError,
    ProductUrlValidationError,
    import_single_product_candidate,
    merchant_name_from_url,
)
from app.curation.source_scan_guardrails import (
    clean_merchant_name,
    get_merchant_source_guidance,
    normalize_category_hint,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])


class CollectionScanRequest(BaseModel):
    collection_id: str | None = Field(None, max_length=64)
    source_url: str = Field(..., min_length=8)
    merchant_name: str = Field("Nobody's Child", min_length=2)
    city_mode: CityScanMode | None = None
    target_city_slug: str | None = Field(None, min_length=2)
    normalized_category: str | None = None
    source: str = Field("shopify", min_length=2)
    source_type: str = Field("collection", min_length=2)
    limit: int = Field(30, ge=1, le=100)
    image_mode: Literal["fast", "smart", "model_only"] = "smart"
    merchant_source_confirmed: bool = False

    @field_validator("source_url", "source", "source_type", mode="before")
    @classmethod
    def strip_text_fields(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("merchant_name", mode="before")
    @classmethod
    def normalize_merchant_whitespace(cls, value):
        return clean_merchant_name(value) if isinstance(value, str) else value

    @field_validator("target_city_slug", mode="before")
    @classmethod
    def normalize_city_slug(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return value.strip().lower().replace("_", "-").replace(" ", "-")

    @model_validator(mode="after")
    def validate_city_scan_intent(self):
        if self.city_mode is None:
            self.city_mode = (
                CityScanMode.SELECTED
                if self.target_city_slug
                else CityScanMode.AUTO
            )
        if self.city_mode == CityScanMode.SELECTED and not self.target_city_slug:
            raise ValueError(
                "target_city_slug is required when city_mode is 'selected'"
            )
        if self.city_mode == CityScanMode.AUTO and self.target_city_slug:
            raise ValueError(
                "target_city_slug must be omitted when city_mode is 'auto'"
            )
        return self

    @field_validator("normalized_category", mode="before")
    @classmethod
    def normalize_fallback_category(cls, value):
        return normalize_category_hint(value)


class SingleProductImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(..., min_length=8, max_length=4000)
    source_type: Literal["single_product"] = Field(..., alias="sourceType")
    city_mode: CityScanMode = Field(..., alias="cityMode")
    city_id: str | None = Field(None, alias="cityId", max_length=80)
    category_id: str | None = Field(None, alias="categoryId", max_length=80)

    @field_validator("url", mode="before")
    @classmethod
    def strip_product_url(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("city_id", mode="before")
    @classmethod
    def normalize_city_id(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if cleaned.isdigit():
            return cleaned
        return cleaned.lower().replace("_", "-").replace(" ", "-") or None

    @field_validator("category_id", mode="before")
    @classmethod
    def normalize_category_override(cls, value):
        return normalize_category_hint(value)

    @model_validator(mode="after")
    def validate_city_override(self):
        if self.city_mode == CityScanMode.SELECTED and not self.city_id:
            raise ValueError("cityId is required when cityMode is 'selected'")
        if self.city_mode == CityScanMode.AUTO and self.city_id:
            raise ValueError("cityId must be omitted when cityMode is 'auto'")
        return self


class ReviewCandidateRequest(BaseModel):
    reviewed_by: str = Field("local-admin", min_length=2)
    reason: str | None = None


class ResolveAffiliateLinkRequest(BaseModel):
    force: bool = False


class InvalidateAffiliateLinkRequest(BaseModel):
    reason: str | None = Field(None, max_length=500)


class PublishCandidateRequest(BaseModel):
    published_by: str = Field("curator-studio", min_length=2)


class PublishApprovedCandidatesRequest(BaseModel):
    published_by: str = Field("curator-studio", min_length=2)
    target_city_slug: str | None = None
    limit: int = Field(50, ge=1, le=200)


class ArchiveCandidateRequest(BaseModel):
    archived_by: str = Field("curator-studio", min_length=2)
    reason: str | None = None


class RestoreCandidateRequest(BaseModel):
    restored_by: str = Field("curator-studio", min_length=2)
    restore_to: str = Field("pending", min_length=2)


def _admin_identity(admin_user) -> str:
    return str(
        getattr(admin_user, "email", None)
        or getattr(admin_user, "id", None)
        or "authenticated-admin"
    )


class ScoringSettingsUpdateRequest(BaseModel):
    enabled: bool
    updated_by: str = Field("curator-studio", min_length=2, max_length=255)


class CollectionActiveRequest(BaseModel):
    is_active: bool


class RescoreCandidateRequest(BaseModel):
    observed_garment_details: list[str] | None = Field(
        None,
        max_length=20,
    )
    rescored_by: str = Field("curator-studio", min_length=2, max_length=255)
    reassign_automatically: bool = False

    @field_validator("observed_garment_details", mode="before")
    @classmethod
    def clean_observed_details(cls, value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("observed_garment_details must be a list")
        cleaned = [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]
        if any(len(item) > 500 for item in cleaned):
            raise ValueError("Each observed garment detail must be 500 characters or less")
        return cleaned


class CityAssignmentRequest(BaseModel):
    target_city_slug: str = Field(..., min_length=2, max_length=80)
    assigned_by: str = Field("curator-studio", min_length=2, max_length=255)

    @field_validator("target_city_slug", mode="before")
    @classmethod
    def normalize_target_city_slug(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip().lower().replace("_", "-").replace(" ", "-")


class MapConceptProposalRequest(BaseModel):
    concept_id: str = Field(..., min_length=1, max_length=120)
    reviewed_by: str = Field("curator-studio", min_length=2)


class CreateConceptProposalRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    concept_id: str | None = Field(None, max_length=120)
    category: str = Field(..., min_length=2, max_length=80)
    traits: list[str] = Field(default_factory=list, max_length=30)
    reviewed_by: str = Field("curator-studio", min_length=2)


class RejectConceptProposalRequest(BaseModel):
    reviewed_by: str = Field("curator-studio", min_length=2)


class BrandAssetResolveRequest(BaseModel):
    brand_name: str = Field(..., min_length=2)
    target_city_slug: str = Field(..., min_length=2)
    logo_url: str | None = Field(None, alias="logoUrl")

    class Config:
        allow_population_by_field_name = True


@router.get("/awin-normalized")
def list_awin_normalized(
    status: str | None = Query(None),
    usable_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(AwinProductNormalized).order_by(AwinProductNormalized.id.desc())

    if status:
        query = query.filter(AwinProductNormalized.review_status == status)

    if usable_only:
        query = query.filter(AwinProductNormalized.is_usable.is_(True))

    rows = query.offset(offset).limit(limit).all()

    return {
        "items": [
            {
                "id": row.id,
                "external_product_id": row.external_product_id,
                "advertiser_id": row.advertiser_id,
                "advertiser_name": row.advertiser_name,
                "title": row.title,
                "brand_name": row.brand_name,
                "price_amount": str(row.price_amount) if row.price_amount is not None else None,
                "currency": row.currency,
                "availability": row.availability,
                "normalized_category": row.normalized_category,
                "is_usable": row.is_usable,
                "needs_review": row.needs_review,
                "review_status": row.review_status,
                "review_notes": row.review_notes,
                "rejection_reason": row.rejection_reason,
                "promoted_product_id": row.promoted_product_id,
                "promoted_at": row.promoted_at,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.patch("/awin-normalized/{row_id}/approve")
def approve_awin_normalized(
    row_id: int,
    reviewed_by: str = Query("local-admin"),
    db: Session = Depends(get_db),
):
    row = db.query(AwinProductNormalized).filter(AwinProductNormalized.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    row.review_status = "approved"
    row.needs_review = False
    row.reviewed_by = reviewed_by
    row.reviewed_at = datetime.now(timezone.utc)
    row.rejection_reason = None

    db.commit()
    return {"status": "ok", "row_id": row.id, "review_status": row.review_status}


@router.patch("/awin-normalized/{row_id}/reject")
def reject_awin_normalized(
    row_id: int,
    reason: str = Query(..., min_length=3),
    reviewed_by: str = Query("local-admin"),
    db: Session = Depends(get_db),
):
    row = db.query(AwinProductNormalized).filter(AwinProductNormalized.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    row.review_status = "rejected"
    row.needs_review = False
    row.reviewed_by = reviewed_by
    row.reviewed_at = datetime.now(timezone.utc)
    row.rejection_reason = reason

    db.commit()
    return {"status": "ok", "row_id": row.id, "review_status": row.review_status}


@router.patch("/awin-normalized/{row_id}/suppress")
def suppress_awin_normalized(
    row_id: int,
    reason: str = Query(..., min_length=3),
    reviewed_by: str = Query("local-admin"),
    db: Session = Depends(get_db),
):
    row = db.query(AwinProductNormalized).filter(AwinProductNormalized.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    row.review_status = "suppressed"
    row.needs_review = False
    row.reviewed_by = reviewed_by
    row.reviewed_at = datetime.now(timezone.utc)
    row.rejection_reason = reason

    db.commit()
    return {"status": "ok", "row_id": row.id, "review_status": row.review_status}


@router.get("/brand-controls")
def list_brand_controls(db: Session = Depends(get_db)):
    rows = (
        db.query(CatalogBrandControl)
        .order_by(CatalogBrandControl.source.asc(), CatalogBrandControl.display_name.asc())
        .all()
    )

    return {
        "items": [
            {
                "id": row.id,
                "source": row.source,
                "brand_key": row.brand_key,
                "display_name": row.display_name,
                "origin_country_code": row.origin_country_code,
                "is_allowed": row.is_allowed,
                "notes": row.notes,
            }
            for row in rows
        ]
    }



def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def _clean_source_url_for_filter(source_url: str | None) -> str | None:
    cleaned = _clean_text(source_url)
    if not cleaned:
        return None

    parsed = urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        return cleaned

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _apply_candidate_source_filters(
    query,
    *,
    merchant_name: str | None = None,
    source_url: str | None = None,
    scan_run_id: str | None = None,
    source_host: str | None = None,
    scanned_only: bool = False,
):
    cleaned_merchant = _clean_text(merchant_name)
    if cleaned_merchant:
        query = query.filter(func.lower(ProductCandidate.merchant_name) == cleaned_merchant.lower())

    cleaned_source_url = _clean_source_url_for_filter(source_url)
    if cleaned_source_url:
        query = query.filter(ProductCandidate.source_url == cleaned_source_url)

    query = apply_scan_run_candidate_filter(query, scan_run_id)
    query = apply_store_candidate_filter(query, source_host)
    if scanned_only:
        query = apply_scanned_candidate_filter(query)

    return query


def _brand_lookup_name(candidate: ProductCandidate) -> str:
    return (
        _clean_text(candidate.brand_name)
        or _clean_text(candidate.merchant_name)
        or "Unknown Store"
    )



def _find_brand_for_city(db: Session, *, brand_name: str, city: City) -> Brand | None:
    return (
        db.query(Brand)
        .filter(Brand.country_id == city.country_id)
        .filter(func.lower(Brand.name) == brand_name.lower())
        .first()
    )


def _brand_asset_payload(
    *,
    brand_name: str,
    city: City,
    brand: Brand | None,
    candidate_count: int,
    latest_candidate_id: int | None,
    latest_candidate_title: str | None,
    latest_source_url: str | None,
    latest_scan_run_id: str | None = None,
) -> dict:
    logo_url = _clean_text(brand.logo_url if brand else None)
    country = city.country

    return {
        "brand_name": brand.name if brand else brand_name,
        "target_city_slug": city.slug,
        "target_city_name": city.name,
        "country_code": country.code if country else None,
        "country_name": country.name if country else None,
        "brand_exists": brand is not None,
        "brand_id": brand.id if brand else None,
        "logo_url": logo_url,
        "logo_status": "ready" if logo_url else "missing",
        "candidate_count": candidate_count,
        "latest_candidate_id": latest_candidate_id,
        "latest_candidate_title": latest_candidate_title,
        "latest_source_url": latest_source_url,
        "latest_scan_run_id": latest_scan_run_id,
    }


@router.get("/brand-assets")
def list_brand_assets(
    target_city_slug: str | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
    merchant_name: str | None = Query(None),
    source_url: str | None = Query(None),
    scan_run_id: str | None = Query(None),
    source_host: str | None = Query(None),
    scanned_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Summarize stores discovered from candidate products and their logo readiness."""
    query = db.query(ProductCandidate).order_by(ProductCandidate.id.desc())

    if target_city_slug:
        query = query.filter(ProductCandidate.target_city_slug == target_city_slug)
    try:
        query = apply_candidate_queue_filter(query, status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source:
        query = query.filter(ProductCandidate.source == source)
    query = _apply_candidate_source_filters(
        query,
        merchant_name=merchant_name,
        source_url=source_url,
        scan_run_id=scan_run_id,
        source_host=source_host,
        scanned_only=scanned_only,
    )

    rows = query.limit(limit).all()
    city_slugs = sorted(
        {
            row.target_city_slug
            for row in rows
            if row.target_city_slug
        }
    )
    cities = {
        city.slug: city
        for city in db.query(City).filter(City.slug.in_(city_slugs)).all()
    } if city_slugs else {}

    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        city = cities.get(row.target_city_slug)
        if not city:
            continue

        brand_name = _brand_lookup_name(row)
        key = (city.slug, brand_name.strip().lower())
        group = grouped.setdefault(
            key,
            {
                "brand_name": brand_name,
                "city": city,
                "candidate_count": 0,
                "latest_candidate_id": None,
                "latest_candidate_title": None,
                "latest_source_url": None,
                "latest_scan_run_id": None,
            },
        )
        group["candidate_count"] += 1
        if group["latest_candidate_id"] is None or row.id > group["latest_candidate_id"]:
            group["latest_candidate_id"] = row.id
            group["latest_candidate_title"] = row.title
            group["latest_source_url"] = row.source_url
            group["latest_scan_run_id"] = row.scan_run_id

    items: list[dict] = []
    for group in grouped.values():
        city = group["city"]
        brand_name = group["brand_name"]
        brand = _find_brand_for_city(db, brand_name=brand_name, city=city)
        items.append(
            _brand_asset_payload(
                brand_name=brand_name,
                city=city,
                brand=brand,
                candidate_count=group["candidate_count"],
                latest_candidate_id=group["latest_candidate_id"],
                latest_candidate_title=group["latest_candidate_title"],
                latest_source_url=group["latest_source_url"],
                latest_scan_run_id=group.get("latest_scan_run_id"),
            )
        )

    items.sort(key=lambda item: (item["logo_status"] == "ready", item["brand_name"].lower()))

    return {"items": items, "count": len(items)}


@router.post("/brand-assets/resolve")
def resolve_brand_asset(
    payload: BrandAssetResolveRequest,
    db: Session = Depends(get_db),
):
    brand_name = _clean_text(payload.brand_name)
    if not brand_name:
        raise HTTPException(status_code=400, detail="Brand name is required")

    city = db.query(City).filter(City.slug == payload.target_city_slug).first()
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{payload.target_city_slug}' was not found")

    logo_url = _clean_text(payload.logo_url)
    brand = _find_brand_for_city(db, brand_name=brand_name, city=city)
    action = "updated" if brand else "created"

    if brand:
        brand.logo_url = logo_url
    else:
        brand = Brand(name=brand_name, country_id=city.country_id, logo_url=logo_url)
        db.add(brand)

    db.commit()
    db.refresh(brand)

    return {
        "status": "ok",
        "action": action,
        "item": _brand_asset_payload(
            brand_name=brand_name,
            city=city,
            brand=brand,
            candidate_count=0,
            latest_candidate_id=None,
            latest_candidate_title=None,
            latest_source_url=None,
            latest_scan_run_id=None,
        ),
    }


def _parse_active_filter(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized == "all":
        return None
    if normalized == "active":
        return True
    if normalized == "inactive":
        return False
    raise HTTPException(
        status_code=400,
        detail="Active filter must be active, inactive, or all",
    )


def _collection_matches_scan_filters(
    item: dict,
    *,
    scan_status: str,
    has_products: bool | None,
) -> bool:
    normalized_status = scan_status.strip().lower()
    allowed_statuses = {
        "all",
        "never_scanned",
        "previously_scanned",
        "running",
        "completed",
        "succeeded",
        "failed",
    }
    if normalized_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                "Scan status must be all, never_scanned, previously_scanned, "
                "running, completed, succeeded, or failed"
            ),
        )

    last_status = item["last_scan_status"]
    if normalized_status == "never_scanned" and last_status != "never_scanned":
        return False
    if normalized_status == "previously_scanned" and last_status == "never_scanned":
        return False
    if normalized_status in {"completed", "succeeded"} and last_status != "completed":
        return False
    if normalized_status in {"running", "failed"} and last_status != normalized_status:
        return False
    if has_products is not None and item["has_products"] is not has_products:
        return False
    return True


def _merchant_summary_payload(
    merchant: Merchant,
    *,
    collections: list[MerchantCollection],
    collection_items: list[dict],
) -> dict:
    last_activity = max(
        (
            item["last_scanned_at"]
            for item in collection_items
            if item["last_scanned_at"]
        ),
        default=None,
    )
    return {
        "id": merchant.id,
        "name": merchant.display_name,
        "domain": merchant.canonical_domain,
        "is_active": merchant.is_active,
        "import_batch": merchant.import_batch,
        "collection_count": len(collections),
        "active_collection_count": sum(
            1 for collection in collections if collection.is_active
        ),
        "matching_collection_count": len(collection_items),
        "last_activity_at": last_activity,
    }


@router.get("/merchants")
def list_merchants(
    search: str | None = Query(None),
    category: str | None = Query(None),
    city: str | None = Query(None),
    active: str = Query("active"),
    collection_active: str = Query("active"),
    scan_status: str = Query("all"),
    has_products: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    merchant_active = _parse_active_filter(active)
    selected_collection_active = _parse_active_filter(collection_active)
    query = db.query(Merchant)
    if merchant_active is not None:
        query = query.filter(Merchant.is_active.is_(merchant_active))

    search_value = (_clean_text(search) or "").lower()
    cleaned_category = _clean_text(category)
    cleaned_city = _clean_text(city)
    if search_value:
        search_pattern = f"%{search_value}%"
        collection_search = (
            exists()
            .where(MerchantCollection.merchant_id == Merchant.id)
            .where(
                or_(
                    func.lower(MerchantCollection.collection_name).like(search_pattern),
                    func.lower(MerchantCollection.collection_url).like(search_pattern),
                    func.lower(
                        func.coalesce(MerchantCollection.canonical_category, "")
                    ).like(search_pattern),
                )
            )
        )
        query = query.filter(
            or_(
                func.lower(Merchant.display_name).like(search_pattern),
                func.lower(Merchant.canonical_domain).like(search_pattern),
                collection_search,
            )
        )
    if cleaned_category:
        query = query.filter(
            exists()
            .where(MerchantCollection.merchant_id == Merchant.id)
            .where(MerchantCollection.canonical_category == cleaned_category)
        )
    if cleaned_city:
        query = query.filter(
            exists()
            .where(MerchantCollection.merchant_id == Merchant.id)
            .where(MerchantCollection.city_slug == cleaned_city)
        )

    merchants = query.order_by(Merchant.display_name.asc()).all()
    merchant_ids = [merchant.id for merchant in merchants]
    all_collections = (
        db.query(MerchantCollection)
        .filter(MerchantCollection.merchant_id.in_(merchant_ids))
        .order_by(
            MerchantCollection.merchant_id.asc(),
            MerchantCollection.collection_name.asc(),
        )
        .all()
        if merchant_ids
        else []
    )
    latest_runs = latest_scan_runs_by_collection(
        db,
        [collection.id for collection in all_collections],
    )
    collections_by_merchant: dict[str, list[MerchantCollection]] = {}
    for collection in all_collections:
        collections_by_merchant.setdefault(collection.merchant_id, []).append(collection)

    items: list[dict] = []
    for merchant in merchants:
        merchant_collections = collections_by_merchant.get(merchant.id, [])
        matching_items: list[dict] = []
        for collection in merchant_collections:
            if (
                selected_collection_active is not None
                and collection.is_active is not selected_collection_active
            ):
                continue
            if cleaned_category and collection.canonical_category != cleaned_category:
                continue
            if cleaned_city and collection.city_slug != cleaned_city:
                continue
            item = collection_payload(
                collection,
                merchant=merchant,
                latest_run=latest_runs.get(collection.id),
            )
            if not _collection_matches_scan_filters(
                item,
                scan_status=scan_status,
                has_products=has_products,
            ):
                continue
            matching_items.append(item)
        if not matching_items and (
            cleaned_category
            or cleaned_city
            or selected_collection_active is not None
            or scan_status != "all"
            or has_products is not None
        ):
            continue
        items.append(
            _merchant_summary_payload(
                merchant,
                collections=merchant_collections,
                collection_items=matching_items,
            )
        )

    total = len(items)
    return {
        "items": items[offset : offset + limit],
        "count": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/merchant-collections")
def list_merchant_collections(
    merchant_id: str | None = Query(None),
    search: str | None = Query(None),
    category: str | None = Query(None),
    city: str | None = Query(None),
    active: str = Query("active"),
    scan_status: str = Query("all"),
    has_products: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    selected_active = _parse_active_filter(active)
    query = db.query(MerchantCollection).join(
        Merchant,
        Merchant.id == MerchantCollection.merchant_id,
    )
    if merchant_id:
        query = query.filter(MerchantCollection.merchant_id == merchant_id)
    if selected_active is not None:
        query = query.filter(MerchantCollection.is_active.is_(selected_active))
    if category:
        query = query.filter(MerchantCollection.canonical_category == category)
    if city:
        query = query.filter(MerchantCollection.city_slug == city)

    search_value = (_clean_text(search) or "").lower()
    if search_value:
        search_pattern = f"%{search_value}%"
        query = query.filter(
            or_(
                func.lower(Merchant.display_name).like(search_pattern),
                func.lower(Merchant.canonical_domain).like(search_pattern),
                func.lower(MerchantCollection.collection_name).like(search_pattern),
                func.lower(MerchantCollection.collection_url).like(search_pattern),
                func.lower(
                    func.coalesce(MerchantCollection.canonical_category, "")
                ).like(search_pattern),
            )
        )

    collections = query.order_by(
        Merchant.display_name.asc(),
        MerchantCollection.collection_name.asc(),
    ).all()
    latest_runs = latest_scan_runs_by_collection(
        db,
        [collection.id for collection in collections],
    )
    items = [
        collection_payload(
            collection,
            latest_run=latest_runs.get(collection.id),
        )
        for collection in collections
    ]
    items = [
        item
        for item in items
        if _collection_matches_scan_filters(
            item,
            scan_status=scan_status,
            has_products=has_products,
        )
    ]
    total = len(items)
    return {
        "items": items[offset : offset + limit],
        "count": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/merchants/{merchant_id}")
def get_merchant(
    merchant_id: str,
    db: Session = Depends(get_db),
):
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    collections = (
        db.query(MerchantCollection)
        .filter(MerchantCollection.merchant_id == merchant.id)
        .order_by(MerchantCollection.collection_name.asc())
        .all()
    )
    latest_runs = latest_scan_runs_by_collection(
        db,
        [collection.id for collection in collections],
    )
    collection_items = [
        collection_payload(
            collection,
            merchant=merchant,
            latest_run=latest_runs.get(collection.id),
        )
        for collection in collections
    ]
    return {
        **_merchant_summary_payload(
            merchant,
            collections=collections,
            collection_items=collection_items,
        ),
        "collections": collection_items,
    }


@router.patch("/merchant-collections/{collection_id}")
def update_merchant_collection(
    collection_id: str,
    payload: CollectionActiveRequest,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    collection = (
        db.query(MerchantCollection)
        .filter(MerchantCollection.id == collection_id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Merchant collection not found")
    collection.is_active = payload.is_active
    db.commit()
    db.refresh(collection)
    latest_run = (
        db.query(CurationScanRun)
        .filter(CurationScanRun.collection_id == collection.id)
        .order_by(CurationScanRun.started_at.desc(), CurationScanRun.id.desc())
        .first()
    )
    return collection_payload(collection, latest_run=latest_run)


@router.get("/scan-stores")
def list_scan_stores(
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    items = list_scanned_stores(db, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/scan-runs")
def list_scan_runs(
    status: str | None = Query(None),
    target_city_slug: str | None = Query(None),
    merchant_name: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(CurationScanRun)
    cleaned_status = (_clean_text(status) or "all").lower()
    if cleaned_status not in {"all", "running", "completed", "failed"}:
        raise HTTPException(
            status_code=400,
            detail="Scan status must be running, completed, failed, or all",
        )
    if cleaned_status != "all":
        query = query.filter(CurationScanRun.status == cleaned_status)
    if target_city_slug:
        query = query.filter(CurationScanRun.target_city_slug == target_city_slug)
    cleaned_merchant = _clean_text(merchant_name)
    if cleaned_merchant:
        query = query.filter(
            func.lower(CurationScanRun.merchant_name) == cleaned_merchant.lower()
        )

    total = query.count()
    rows = (
        query.order_by(CurationScanRun.started_at.desc(), CurationScanRun.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    run_ids = [row.id for row in rows]
    candidate_counts = {
        run_id: count
        for run_id, count in (
            db.query(
                CurationScanRunCandidate.scan_run_id,
                func.count(CurationScanRunCandidate.candidate_id),
            )
            .filter(CurationScanRunCandidate.scan_run_id.in_(run_ids))
            .group_by(CurationScanRunCandidate.scan_run_id)
            .all()
        )
    } if run_ids else {}

    return {
        "items": [
            scan_run_payload(
                row,
                candidate_count=int(candidate_counts.get(row.id, 0)),
            )
            for row in rows
        ],
        "count": total,
    }


@router.get("/scan-runs/{scan_run_id}")
def get_scan_run(
    scan_run_id: str,
    db: Session = Depends(get_db),
):
    run = db.query(CurationScanRun).filter(CurationScanRun.id == scan_run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Scan run not found")
    candidate_count = (
        db.query(func.count(CurationScanRunCandidate.candidate_id))
        .filter(CurationScanRunCandidate.scan_run_id == run.id)
        .scalar()
        or 0
    )
    return scan_run_payload(run, candidate_count=int(candidate_count))


@router.get("/scan-runs/{scan_run_id}/observability")
def get_scan_run_observability(
    scan_run_id: str,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    run = db.query(CurationScanRun).filter(CurationScanRun.id == scan_run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return build_scan_observability(db, run)


@router.get("/scoring-settings")
def get_scoring_settings(
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    return get_curation_scoring_configuration(db).as_dict()


@router.patch("/scoring-settings")
def update_scoring_settings(
    payload: ScoringSettingsUpdateRequest,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    return set_curation_scoring_configuration(
        db,
        enabled=payload.enabled,
        updated_by=payload.updated_by,
    ).as_dict()


def _resolve_single_product_city_slug(
    db: Session,
    city_id: str | None,
) -> str | None:
    if not city_id:
        return None
    query = db.query(City)
    row = (
        query.filter(City.id == int(city_id)).first()
        if city_id.isdigit()
        else query.filter(City.slug == city_id).first()
    )
    if not row:
        raise ValueError(
            f"City '{city_id}' does not exist in the Haroona API yet."
        )
    return row.slug


@router.post("/single-product-import")
def import_single_product(
    payload: SingleProductImportRequest,
    db: Session = Depends(get_db),
):
    try:
        target_city_slug = _resolve_single_product_city_slug(db, payload.city_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_single_product_city",
                "message": str(exc),
            },
        ) from exc
    active_city_slugs = active_scoring_city_slugs(db)
    if not active_city_slugs:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "single_product_city_configuration_missing",
                "message": (
                    "Single-product analysis requires at least one registered "
                    "Haroona city with a scoring profile."
                ),
            },
        )
    if (
        payload.city_mode == CityScanMode.SELECTED
        and target_city_slug not in active_city_slugs
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "type": "single_product_city_not_active",
                "message": (
                    f"City '{target_city_slug}' is not an active Haroona scoring city."
                ),
            },
        )

    scan_run_id = f"scan_{uuid4().hex}"
    provisional_merchant_name = merchant_name_from_url(payload.url)
    scan_run = start_scan_run(
        db,
        scan_run_id=scan_run_id,
        source_url=payload.url,
        merchant_name=provisional_merchant_name,
        target_city_slug=target_city_slug,
        normalized_category=payload.category_id,
        requested_image_mode="fast",
        requested_limit=1,
        city_mode=payload.city_mode.value,
    )
    update_scan_run_context(
        db,
        scan_run,
        merchant_name=provisional_merchant_name,
        scanner_name="single_product_page",
        source="single_product",
        source_type="single_product",
        merchant_verification="unverified",
        effective_image_mode="fast",
    )
    try:
        result = import_single_product_candidate(
            db,
            url=payload.url,
            city_mode=payload.city_mode,
            target_city_slug=target_city_slug,
            category_override=payload.category_id,
            active_city_slugs=active_city_slugs,
            scan_run_id=scan_run_id,
            concept_overrides=load_runtime_concept_overrides(db),
            scoring_mode=get_curation_scoring_configuration(db).scoring_mode,
        )
        update_scan_run_context(
            db,
            scan_run,
            merchant_name=result["merchant_name"],
            scanner_name="single_product_page",
            source="single_product",
            source_type="single_product",
            merchant_verification=(
                result["candidate"].get("merchant_verification")
                or "unverified"
            ),
            effective_image_mode="fast",
        )
        try:
            concept_review = record_unknown_concepts_for_scan(db, scan_run_id)
        except Exception:
            db.rollback()
            logger.exception(
                "Concept proposal indexing failed for single product %s",
                scan_run_id,
            )
            concept_review = {
                "detected": 0,
                "created": 0,
                "updated": 0,
                "skipped": 1,
            }
            result["warnings"].append(
                "The product was saved, but concept-review indexing was skipped "
                "because of a temporary database conflict."
            )
        result["concept_review"] = concept_review
        if isinstance(result.get("summary"), dict):
            result["summary"]["concept_review"] = concept_review
        complete_scan_run(
            db,
            scan_run,
            result=result,
            warnings=result.get("warnings") or [],
        )
        return result
    except ProductUrlValidationError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="invalid_single_product_url",
            attempts=list(exc.attempts),
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_single_product_url",
                "message": str(exc),
                "suggestion": (
                    "Paste a public retailer product-detail URL beginning with "
                    "https://."
                ),
            },
        ) from exc
    except NotProductPageError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="not_a_product_page",
            attempts=list(exc.attempts),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "type": "not_a_product_page",
                "message": str(exc),
                "attempts": list(exc.attempts),
                "suggestion": (
                    "Open the exact item page—not a collection, category, search, "
                    "or store homepage—and try that URL."
                ),
            },
        ) from exc
    except ProductPageFetchError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="single_product_fetch_failed",
            attempts=list(exc.attempts),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "type": "single_product_fetch_failed",
                "message": str(exc),
                "attempts": list(exc.attempts),
                "suggestion": (
                    "Confirm that the exact product page is public. Some retailers "
                    "block automated page access."
                ),
            },
        ) from exc
    except ValueError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="invalid_single_product_import",
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_single_product_import",
                "message": str(exc),
                "suggestion": (
                    "Check the product URL, category override, and city override."
                ),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Single-product import %s failed", scan_run_id)
        fail_scan_run(
            db,
            scan_run_id,
            error_message=type(exc).__name__,
            failure_type="single_product_import_failed",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "type": "single_product_import_failed",
                "message": (
                    "Single-product analysis failed during an internal processing "
                    "step. No database details were exposed."
                ),
            },
        ) from exc


@router.post("/collection-scan")
def scan_collection(
    payload: CollectionScanRequest,
    db: Session = Depends(get_db),
):
    catalog_collection: MerchantCollection | None = None
    if payload.collection_id:
        catalog_collection = (
            db.query(MerchantCollection)
            .filter(MerchantCollection.id == payload.collection_id)
            .first()
        )
        if not catalog_collection:
            raise HTTPException(
                status_code=404,
                detail="Merchant collection not found",
            )
        if not catalog_collection.is_active:
            raise HTTPException(
                status_code=400,
                detail="Inactive merchant collections cannot be scanned",
            )
        try:
            submitted_url, _ = normalize_collection_url(payload.source_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if submitted_url != catalog_collection.normalized_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The submitted URL does not match the selected merchant "
                    "collection"
                ),
            )
        payload = payload.model_copy(
            update={
                "source_url": catalog_collection.collection_url,
                "merchant_name": catalog_collection.merchant.display_name,
                "normalized_category": (
                    payload.normalized_category
                    or catalog_collection.canonical_category
                ),
                "merchant_source_confirmed": True,
            }
        )

    scan_run_id = f"scan_{uuid4().hex}"
    scan_run = start_scan_run(
        db,
        scan_run_id=scan_run_id,
        source_url=payload.source_url,
        merchant_name=payload.merchant_name,
        target_city_slug=payload.target_city_slug,
        normalized_category=payload.normalized_category,
        requested_image_mode=payload.image_mode,
        requested_limit=payload.limit,
        collection_id=catalog_collection.id if catalog_collection else None,
        city_mode=payload.city_mode.value,
    )
    try:
        scanner = detect_curation_scanner(payload.source_url)
        merchant_guidance = get_merchant_source_guidance(
            payload.source_url,
            payload.merchant_name,
        )
        if merchant_guidance.verification == "conflict":
            raise ValueError(merchant_guidance.message)
        if (
            merchant_guidance.verification == "unverified"
            and not payload.merchant_source_confirmed
        ):
            raise ValueError(
                "Confirm that the merchant name matches the unverified source domain "
                "before scanning."
            )

        active_city_slugs = active_scoring_city_slugs(db)
        if payload.city_mode == CityScanMode.SELECTED:
            city_exists = (
                db.query(City.id)
                .filter(City.slug == payload.target_city_slug)
                .first()
            )
            if not city_exists:
                raise ValueError(
                    f"City '{payload.target_city_slug}' does not exist in the Haroona API yet."
                )
        elif not active_city_slugs:
            raise ValueError(
                "Automatic city detection requires at least one registered "
                "Haroona city with a scoring profile."
            )

        requested_image_mode = payload.image_mode
        effective_image_mode = scanner.resolve_image_mode(requested_image_mode)
        warnings: list[str] = []
        if merchant_guidance.verification == "unverified" and merchant_guidance.message:
            warnings.append(merchant_guidance.message)
        if effective_image_mode != requested_image_mode:
            warnings.append(
                f"{scanner.name} currently supports "
                f"{', '.join(scanner.supported_image_modes)} image mode only; "
                f"the scan used {effective_image_mode}."
            )

        update_scan_run_context(
            db,
            scan_run,
            merchant_name=merchant_guidance.resolved_name,
            scanner_name=scanner.name,
            source=scanner.source,
            source_type=scanner.source_type,
            merchant_verification=merchant_guidance.verification,
            effective_image_mode=effective_image_mode,
        )
        options = CollectionScanOptions(
            source_url=payload.source_url,
            merchant_name=merchant_guidance.resolved_name,
            target_city_slug=payload.target_city_slug,
            city_mode=payload.city_mode.value,
            active_city_slugs=active_city_slugs,
            normalized_category=payload.normalized_category,
            source=scanner.source,
            source_type=scanner.source_type,
            limit=payload.limit,
            image_mode=effective_image_mode,
            scan_run_id=scan_run_id,
            merchant_verification=merchant_guidance.verification,
            merchant_profile_allowed=merchant_guidance.verification == "verified",
            concept_overrides=load_runtime_concept_overrides(db),
            scoring_mode=get_curation_scoring_configuration(db).scoring_mode,
        )

        result = scanner.scan(db, options)
        try:
            concept_review = record_unknown_concepts_for_scan(db, scan_run_id)
        except Exception:
            # Concept proposals are an optional review aid. Product discovery and
            # candidate saving have already committed, so this stage must never
            # turn a successful collection scan into a 502 response.
            db.rollback()
            logger.exception(
                "Concept proposal indexing failed for scan %s", scan_run_id
            )
            concept_review = {
                "detected": 0,
                "created": 0,
                "updated": 0,
                "skipped": 1,
            }
            warnings.append(
                "Products were saved, but concept-review indexing was skipped "
                "because of a temporary database conflict."
            )
        result["concept_review"] = concept_review
        if isinstance(result.get("summary"), dict):
            result["summary"]["concept_review"] = concept_review
        warnings.extend(result.get("warnings") or [])
        complete_scan_run(
            db,
            scan_run,
            result=result,
            warnings=warnings,
        )
        return {
            **result,
            "scan_run_id": result.get("scan_run_id") or scan_run_id,
            "city_mode": payload.city_mode.value,
            "target_city_slug": payload.target_city_slug,
            "scanner": scanner.name,
            "detected_source": scanner.source,
            "detected_source_type": scanner.source_type,
            "scan_capabilities": {
                "supported_image_modes": list(scanner.supported_image_modes),
                "requested_image_mode": requested_image_mode,
                "effective_image_mode": effective_image_mode,
                "source_host": merchant_guidance.source_host,
                "merchant_verification": merchant_guidance.verification,
                "suggested_merchant_name": merchant_guidance.suggested_name,
            },
            "warnings": warnings,
        }
    except UnsupportedScannerError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="unsupported_curate_studio_url",
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": "unsupported_curate_studio_url",
                "message": str(exc),
                "host": exc.host,
                "path": exc.path,
                "supported_scanners": list(exc.supported_scanners),
                "suggestion": "Use a supported collection/category URL or add a scanner for this store shape.",
            },
        ) from exc
    except ValueError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="invalid_collection_scan_request",
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_collection_scan_request",
                "message": str(exc),
                "suggestion": "Check the URL, city slug, merchant name, and selected image mode, then scan again.",
            },
        ) from exc
    except CollectionRateLimitedError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="collection_source_rate_limited",
            attempts=list(exc.attempts),
        )
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            detail={
                "type": "collection_source_rate_limited",
                "message": str(exc),
                "attempts": list(exc.attempts),
                "retry_after_seconds": exc.retry_after_seconds,
                "suggestion": (
                    "Wait for the displayed cooldown before requesting a fresh scan. "
                    "If Haroona has a saved snapshot for this exact collection URL, "
                    "it will reuse and rescore that snapshot automatically."
                ),
            },
        ) from exc
    except CollectionDiscoveryError as exc:
        fail_scan_run(
            db,
            scan_run_id,
            error_message=str(exc),
            failure_type="collection_discovery_failed",
            attempts=list(exc.attempts),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "type": "collection_discovery_failed",
                "message": str(exc),
                "attempts": list(exc.attempts),
                "suggestion": (
                    "The store may block automated access or hide product data. "
                    "Try another public collection/category URL from the same store; "
                    "changing image mode will not repair product discovery."
                ),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Collection scan %s failed", scan_run_id)
        fail_scan_run(
            db,
            scan_run_id,
            error_message=type(exc).__name__,
            failure_type="collection_scan_failed",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "type": "collection_scan_failed",
                "message": (
                    "Collection scan failed during an internal processing step. "
                    "No database query details were exposed."
                ),
                "suggestion": (
                    "Review the recent scan error and verify that the collection URL is public. "
                    "Image mode changes image selection after products are discovered."
                ),
            },
        ) from exc


@router.get("/fashion-concepts")
def list_fashion_concepts(
    search: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    items = list_available_concepts(db, search=search, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "categories": list(CONCEPT_CATEGORIES),
    }


@router.get("/concept-proposals")
def list_concept_proposals(
    status: str = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    normalized_status = status.strip().lower()
    allowed_statuses = {"pending", "mapped", "created", "rejected", "all"}
    if normalized_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Unsupported concept proposal status")
    query = db.query(FashionConceptProposal)
    if normalized_status != "all":
        query = query.filter(FashionConceptProposal.status == normalized_status)
    total = query.count()
    rows = (
        query.order_by(
            FashionConceptProposal.occurrence_count.desc(),
            FashionConceptProposal.last_seen_at.desc(),
            FashionConceptProposal.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": [proposal_payload(row) for row in rows], "count": total}


@router.post("/concept-proposals/{proposal_id}/map")
def map_concept_proposal(
    proposal_id: int,
    payload: MapConceptProposalRequest,
    db: Session = Depends(get_db),
):
    try:
        row = map_proposal_to_concept(
            db,
            proposal_id,
            concept_id=payload.concept_id,
            reviewed_by=payload.reviewed_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "proposal": proposal_payload(row)}


@router.post("/concept-proposals/{proposal_id}/create")
def create_concept_proposal(
    proposal_id: int,
    payload: CreateConceptProposalRequest,
    db: Session = Depends(get_db),
):
    try:
        row = create_concept_from_proposal(
            db,
            proposal_id,
            label=payload.label,
            concept_id=payload.concept_id,
            category=payload.category,
            traits=payload.traits,
            reviewed_by=payload.reviewed_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "proposal": proposal_payload(row)}


@router.post("/concept-proposals/{proposal_id}/reject")
def reject_fashion_concept_proposal(
    proposal_id: int,
    payload: RejectConceptProposalRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or RejectConceptProposalRequest()
    try:
        row = reject_concept_proposal(
            db,
            proposal_id,
            reviewed_by=payload.reviewed_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "proposal": proposal_payload(row)}


@router.get("/product-candidates")
def list_product_candidates(
    status: str | None = Query("pending"),
    source: str | None = Query(None),
    target_city_slug: str | None = Query(None),
    final_city_slug: str | None = Query(None),
    recommended_city_slug: str | None = Query(None),
    city_assignment_status: str | None = Query(None),
    merchant_name: str | None = Query(None),
    source_url: str | None = Query(None),
    scan_run_id: str | None = Query(None),
    source_host: str | None = Query(None),
    scanned_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    query = db.query(ProductCandidate).order_by(
        ProductCandidate.haroona_score.desc(),
        ProductCandidate.city_fit_score.desc(),
        ProductCandidate.platform_alignment_score.desc(),
        ProductCandidate.id.desc(),
    )

    try:
        query = apply_candidate_queue_filter(query, status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source:
        query = query.filter(ProductCandidate.source == source)
    if (
        target_city_slug
        and final_city_slug
        and target_city_slug != final_city_slug
    ):
        raise HTTPException(
            status_code=400,
            detail="target_city_slug and final_city_slug must match when both are used",
        )
    selected_final_city_slug = final_city_slug or target_city_slug
    if selected_final_city_slug:
        query = query.filter(
            ProductCandidate.target_city_slug == selected_final_city_slug
        )
    if recommended_city_slug:
        query = query.filter(
            ProductCandidate.recommended_city_slug == recommended_city_slug
        )
    if city_assignment_status:
        normalized_assignment_status = (
            city_assignment_status.strip().lower().replace("-", "_")
        )
        if normalized_assignment_status not in CITY_ASSIGNMENT_STATUSES:
            accepted = ", ".join(sorted(CITY_ASSIGNMENT_STATUSES))
            raise HTTPException(
                status_code=400,
                detail=f"Unknown city assignment status. Use one of: {accepted}",
            )
        query = query.filter(
            ProductCandidate.city_assignment_status
            == normalized_assignment_status
        )
    query = _apply_candidate_source_filters(
        query,
        merchant_name=merchant_name,
        source_url=source_url,
        scan_run_id=scan_run_id,
        source_host=source_host,
        scanned_only=scanned_only,
    )

    rows = query.offset(offset).limit(limit).all()
    product_ids = [row.promoted_product_id for row in rows if row.promoted_product_id]
    product_active_by_id = {
        product.id: product.is_active
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    } if product_ids else {}

    return {
        "items": [
            {
                "id": row.id,
                "source": row.source,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "scan_run_id": row.scan_run_id,
                "merchant_name": row.merchant_name,
                "brand_name": row.brand_name,
                "external_product_id": row.external_product_id,
                "title": row.title,
                "description": row.description,
                "price_amount": str(row.price_amount) if row.price_amount is not None else None,
                "currency": row.currency,
                "affiliate_url": row.affiliate_url,
                "merchant_url": row.merchant_url,
                "original_product_url": row.merchant_url,
                "affiliate_provider": row.affiliate_provider,
                "affiliate_provider_reference": row.affiliate_provider_reference,
                "affiliate_link_status": row.affiliate_link_status,
                "affiliate_sub_id": row.affiliate_sub_id,
                "affiliate_link_attempt_count": row.affiliate_link_attempt_count,
                "affiliate_link_error_code": row.affiliate_link_error_code,
                "affiliate_link_error_message": row.affiliate_link_error_message,
                "affiliate_link_last_attempted_at": row.affiliate_link_last_attempted_at,
                "affiliate_link_generated_at": row.affiliate_link_generated_at,
                "affiliate_link_verified_at": row.affiliate_link_verified_at,
                "affiliate_link_verified_by": row.affiliate_link_verified_by,
                "affiliate_link_invalidated_at": row.affiliate_link_invalidated_at,
                "affiliate_link_invalidated_by": row.affiliate_link_invalidated_by,
                "image_url": row.image_url,
                "availability": row.availability,
                "normalized_category": row.normalized_category,
                "city_scan_mode": row.city_scan_mode,
                "target_city_slug": row.target_city_slug,
                "recommended_city_slug": row.recommended_city_slug,
                "recommended_city_score": row.recommended_city_score,
                "runner_up_city_slug": row.runner_up_city_slug,
                "runner_up_city_score": row.runner_up_city_score,
                "city_score_margin": row.city_score_margin,
                "city_assignment_status": row.city_assignment_status,
                "city_assignment_source": row.city_assignment_source,
                "city_candidates": row.city_candidates or [],
                "manual_city_override": row.manual_city_override,
                "city_assigned_at": row.city_assigned_at,
                "city_assigned_by": row.city_assigned_by,
                "city_connection_type": row.city_connection_type,
                "city_connection_note": row.city_connection_note,
                "merchant_verification": row.merchant_verification,
                "merchant_profile_key": row.merchant_profile_key,
                "eligibility_status": row.eligibility_status,
                "eligibility_reasons": row.eligibility_reasons,
                "platform_alignment_score": (
                    str(row.platform_alignment_score)
                    if row.platform_alignment_score is not None
                    else None
                ),
                "platform_alignment_reasons": row.platform_alignment_reasons,
                "city_fit_score": row.city_fit_score,
                "city_fit_scores": row.city_fit_scores,
                "secondary_city_slug": row.secondary_city_slug,
                "scoring_confidence": row.scoring_confidence,
                "scoring_method": row.scoring_method,
                "scoring_version": row.scoring_version,
                "scoring_mode": row.scoring_mode,
                "scoring_analysis": row.scoring_analysis or {},
                "manual_observed_garment_details": (
                    row.manual_observed_garment_details or []
                ),
                "haroona_score": row.haroona_score,
                "score_reasons": row.score_reasons,
                "review_status": row.review_status,
                "queue_status": resolve_candidate_queue_status(
                    row.review_status,
                    product_active_by_id.get(row.promoted_product_id)
                    if row.promoted_product_id
                    else None,
                ),
                "workflow_status": resolve_candidate_workflow_status(
                    row,
                    product_active_by_id.get(row.promoted_product_id)
                    if row.promoted_product_id
                    else None,
                ),
                "review_notes": row.review_notes,
                "rejection_reason": row.rejection_reason,
                "promoted_product_id": row.promoted_product_id,
                "product_is_active": product_active_by_id.get(row.promoted_product_id) if row.promoted_product_id else None,
                "promoted_at": row.promoted_at,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.post("/product-candidates/{candidate_id}/rescore")
def rescore_candidate(
    candidate_id: int,
    payload: RescoreCandidateRequest | None = None,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or RescoreCandidateRequest()
    observed_details = (
        list(row.manual_observed_garment_details or [])
        if payload.observed_garment_details is None
        else payload.observed_garment_details
    )
    scoring_configuration = get_curation_scoring_configuration(db)
    score = rescore_product_candidate(
        db,
        row,
        scoring_mode=scoring_configuration.scoring_mode,
        manual_observed_garment_details=observed_details,
        rescored_by=payload.rescored_by,
        concept_overrides=load_runtime_concept_overrides(db),
        reassign_automatically=payload.reassign_automatically,
    )
    product_is_active = None
    if row.promoted_product_id:
        product_is_active = (
            db.query(Product.is_active)
            .filter(Product.id == row.promoted_product_id)
            .scalar()
        )
    return {
        "status": "ok",
        "candidate_id": row.id,
        "scoring_mode": score.scoring_mode,
        "scoring_version": score.scoring_version,
        "raw_total": score.raw_total,
        "city_fit_percentage": score.city_fit_percentage,
        "distinctiveness_score": score.distinctiveness_score,
        "primary_match_eligible": score.primary_match_eligible,
        "match_type": score.match_type,
        "gate_failure_reasons": list(score.gate_failure_reasons),
        "target_city_slug": row.target_city_slug,
        "recommended_city_slug": row.recommended_city_slug,
        "recommended_city_score": row.recommended_city_score,
        "runner_up_city_slug": row.runner_up_city_slug,
        "runner_up_city_score": row.runner_up_city_score,
        "city_score_margin": row.city_score_margin,
        "city_assignment_status": row.city_assignment_status,
        "city_assignment_source": row.city_assignment_source,
        "manual_city_override": row.manual_city_override,
        "product_is_active": product_is_active,
        "published_product_changed": False,
    }


@router.patch("/product-candidates/{candidate_id}/city-assignment")
def update_product_candidate_city_assignment(
    candidate_id: int,
    payload: CityAssignmentRequest,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        score = assign_product_candidate_city(
            db,
            row,
            target_city_slug=payload.target_city_slug,
            assigned_by=payload.assigned_by,
            concept_overrides=load_runtime_concept_overrides(db),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ok",
        "candidate_id": row.id,
        "target_city_slug": row.target_city_slug,
        "selected_city_score": (
            score.raw_total if score.raw_total is not None else score.score
        ),
        "recommended_city_slug": row.recommended_city_slug,
        "recommended_city_score": row.recommended_city_score,
        "runner_up_city_slug": row.runner_up_city_slug,
        "runner_up_city_score": row.runner_up_city_score,
        "city_score_margin": row.city_score_margin,
        "city_assignment_status": row.city_assignment_status,
        "city_assignment_source": row.city_assignment_source,
        "manual_city_override": row.manual_city_override,
        "city_candidates": row.city_candidates or [],
    }


@router.post("/product-candidates/publish-approved")
def publish_approved_candidates(
    payload: PublishApprovedCandidatesRequest,
    db: Session = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    return publish_approved_product_candidates(
        db,
        target_city_slug=payload.target_city_slug,
        limit=payload.limit,
        published_by=_admin_identity(admin_user),
    )


@router.post("/product-candidates/{candidate_id}/publish")
def publish_candidate(
    candidate_id: int,
    payload: PublishCandidateRequest | None = None,
    db: Session = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if row.review_status == "archived":
        raise HTTPException(
            status_code=400,
            detail="Archived candidates must be restored before publishing",
        )

    try:
        return publish_product_candidate(
            db,
            row,
            published_by=_admin_identity(admin_user),
        )
    except AffiliateLinkPublicationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@router.patch("/product-candidates/{candidate_id}/archive")
def archive_product_candidate(
    candidate_id: int,
    payload: ArchiveCandidateRequest | None = None,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or ArchiveCandidateRequest()
    reason = _clean_text(payload.reason) or "Archived from Curator Studio"
    try:
        return archive_candidate(
            db,
            row,
            archived_by=payload.archived_by,
            reason=reason,
        )
    except CandidateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/product-candidates/{candidate_id}/restore")
def restore_product_candidate(
    candidate_id: int,
    payload: RestoreCandidateRequest | None = None,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or RestoreCandidateRequest()
    restore_to = (_clean_text(payload.restore_to) or "pending").lower().replace("-", "_")
    try:
        return restore_candidate(
            db,
            row,
            restored_by=payload.restored_by,
            restore_to=restore_to,
        )
    except CandidateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/product-candidates/{candidate_id}/approve")
def approve_product_candidate(
    candidate_id: int,
    payload: ReviewCandidateRequest | None = None,
    db: Session = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        if row.review_status == "approved":
            approval = {
                "status": "ok",
                "candidate_id": row.id,
                "review_status": row.review_status,
                "reused": True,
            }
        else:
            approval = approve_candidate(
                db,
                row,
                reviewed_by=_admin_identity(admin_user),
            )
        db.refresh(row)
        affiliate = resolve_takeads_affiliate_link(db, row)
        return {**approval, "affiliate": affiliate}
    except CandidateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AffiliateLinkTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AffiliateLinkPersistenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/product-candidates/{candidate_id}/affiliate-link")
def get_product_candidate_affiliate_link(
    candidate_id: int,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {
        "status": "ok",
        "candidate_id": row.id,
        "affiliate": affiliate_link_payload(row),
    }


@router.post("/product-candidates/{candidate_id}/affiliate-link/resolve")
def resolve_product_candidate_affiliate_link(
    candidate_id: int,
    payload: ResolveAffiliateLinkRequest | None = None,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        payload = payload or ResolveAffiliateLinkRequest()
        return {
            "status": "ok",
            "candidate_id": row.id,
            "affiliate": resolve_takeads_affiliate_link(
                db,
                row,
                force=payload.force,
            ),
        }
    except AffiliateLinkTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AffiliateLinkPersistenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/product-candidates/{candidate_id}/affiliate-link/verify")
def verify_product_candidate_affiliate_link(
    candidate_id: int,
    db: Session = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        affiliate = verify_candidate_affiliate_link(
            db,
            row,
            verified_by=_admin_identity(admin_user),
        )
        return {
            "status": "ok",
            "candidate_id": row.id,
            "affiliate": affiliate,
        }
    except AffiliateLinkTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AffiliateLinkPersistenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/product-candidates/{candidate_id}/affiliate-link/invalidate")
def invalidate_product_candidate_affiliate_link(
    candidate_id: int,
    payload: InvalidateAffiliateLinkRequest | None = None,
    db: Session = Depends(get_db),
    admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        payload = payload or InvalidateAffiliateLinkRequest()
        affiliate = invalidate_candidate_affiliate_link(
            db,
            row,
            invalidated_by=_admin_identity(admin_user),
            reason=payload.reason,
        )
        return {
            "status": "ok",
            "candidate_id": row.id,
            "affiliate": affiliate,
        }
    except AffiliateLinkTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AffiliateLinkPersistenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.patch("/product-candidates/{candidate_id}/reject")
def reject_product_candidate(
    candidate_id: int,
    payload: ReviewCandidateRequest,
    db: Session = Depends(get_db),
    _admin_user=Depends(get_admin_user),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        return reject_candidate(
            db,
            row,
            reviewed_by=payload.reviewed_by,
            reason=payload.reason or "",
        )
    except CandidateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

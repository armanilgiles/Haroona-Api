from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AwinProductNormalized, Brand, CatalogBrandControl, City, Product, ProductCandidate
from app.curation.product_candidate_publisher import (
    publish_approved_product_candidates,
    publish_product_candidate,
)
from app.curation.scanner_registry import UnsupportedScannerError, detect_curation_scanner
from app.curation.shopify_collection import CollectionScanOptions
from app.curation.source_scan_guardrails import (
    clean_merchant_name,
    get_merchant_source_guidance,
    normalize_category_hint,
)

router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])


class CollectionScanRequest(BaseModel):
    source_url: str = Field(..., min_length=8)
    merchant_name: str = Field("Nobody's Child", min_length=2)
    target_city_slug: str = Field("london", min_length=2)
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
        if not isinstance(value, str):
            return value
        return value.strip().lower().replace("_", "-").replace(" ", "-")

    @field_validator("normalized_category", mode="before")
    @classmethod
    def normalize_fallback_category(cls, value):
        return normalize_category_hint(value)


class ReviewCandidateRequest(BaseModel):
    reviewed_by: str = Field("local-admin", min_length=2)
    reason: str | None = None


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
):
    cleaned_merchant = _clean_text(merchant_name)
    if cleaned_merchant:
        query = query.filter(func.lower(ProductCandidate.merchant_name) == cleaned_merchant.lower())

    cleaned_source_url = _clean_source_url_for_filter(source_url)
    if cleaned_source_url:
        query = query.filter(ProductCandidate.source_url == cleaned_source_url)

    cleaned_scan_run_id = _clean_text(scan_run_id)
    if cleaned_scan_run_id:
        query = query.filter(ProductCandidate.scan_run_id == cleaned_scan_run_id)

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
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Summarize stores discovered from candidate products and their logo readiness."""
    query = db.query(ProductCandidate).order_by(ProductCandidate.id.desc())

    if target_city_slug:
        query = query.filter(ProductCandidate.target_city_slug == target_city_slug)
    if status and status != "all":
        if status == "published":
            query = query.filter(ProductCandidate.promoted_product_id.isnot(None))
            query = query.filter(ProductCandidate.review_status != "archived")
        else:
            query = query.filter(ProductCandidate.review_status == status)
    else:
        query = query.filter(ProductCandidate.review_status != "archived")
    if source:
        query = query.filter(ProductCandidate.source == source)
    query = _apply_candidate_source_filters(
        query,
        merchant_name=merchant_name,
        source_url=source_url,
        scan_run_id=scan_run_id,
    )

    rows = query.limit(limit).all()
    city_slugs = sorted({row.target_city_slug for row in rows})
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


@router.post("/collection-scan")
def scan_collection(
    payload: CollectionScanRequest,
    db: Session = Depends(get_db),
):
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

        city_exists = (
            db.query(City.id)
            .filter(City.slug == payload.target_city_slug)
            .first()
        )
        if not city_exists:
            raise ValueError(
                f"City '{payload.target_city_slug}' does not exist in the Haroona API yet."
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

        scan_run_id = f"scan_{uuid4().hex}"
        options = CollectionScanOptions(
            source_url=payload.source_url,
            merchant_name=merchant_guidance.resolved_name,
            target_city_slug=payload.target_city_slug,
            normalized_category=payload.normalized_category,
            source=scanner.source,
            source_type=scanner.source_type,
            limit=payload.limit,
            image_mode=effective_image_mode,
            scan_run_id=scan_run_id,
        )

        result = scanner.scan(db, options)
        warnings.extend(result.get("warnings") or [])
        return {
            **result,
            "scan_run_id": result.get("scan_run_id") or scan_run_id,
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
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_collection_scan_request",
                "message": str(exc),
                "suggestion": "Check the URL, city slug, merchant name, and selected image mode, then scan again.",
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "type": "collection_scan_failed",
                "message": f"Collection scan failed: {exc}",
                "suggestion": "Try Fast image mode first. If that works, rerun Smart or Model-only mode with a smaller limit.",
            },
        ) from exc


@router.get("/product-candidates")
def list_product_candidates(
    status: str | None = Query("pending"),
    source: str | None = Query(None),
    target_city_slug: str | None = Query(None),
    merchant_name: str | None = Query(None),
    source_url: str | None = Query(None),
    scan_run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(ProductCandidate).order_by(
        ProductCandidate.haroona_score.desc(),
        ProductCandidate.id.desc(),
    )

    if status == "published":
        query = query.join(Product, ProductCandidate.promoted_product_id == Product.id)
        query = query.filter(ProductCandidate.review_status != "archived")
        query = query.filter(Product.is_active.is_(True))
    elif status:
        query = query.filter(ProductCandidate.review_status == status)
    else:
        query = query.filter(ProductCandidate.review_status != "archived")
    if source:
        query = query.filter(ProductCandidate.source == source)
    if target_city_slug:
        query = query.filter(ProductCandidate.target_city_slug == target_city_slug)
    query = _apply_candidate_source_filters(
        query,
        merchant_name=merchant_name,
        source_url=source_url,
        scan_run_id=scan_run_id,
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
                "image_url": row.image_url,
                "availability": row.availability,
                "normalized_category": row.normalized_category,
                "target_city_slug": row.target_city_slug,
                "city_connection_type": row.city_connection_type,
                "city_connection_note": row.city_connection_note,
                "haroona_score": row.haroona_score,
                "score_reasons": row.score_reasons,
                "review_status": row.review_status,
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


@router.post("/product-candidates/publish-approved")
def publish_approved_candidates(
    payload: PublishApprovedCandidatesRequest,
    db: Session = Depends(get_db),
):
    return publish_approved_product_candidates(
        db,
        target_city_slug=payload.target_city_slug,
        limit=payload.limit,
        published_by=payload.published_by,
    )


@router.post("/product-candidates/{candidate_id}/publish")
def publish_candidate(
    candidate_id: int,
    payload: PublishCandidateRequest | None = None,
    db: Session = Depends(get_db),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or PublishCandidateRequest()

    try:
        return publish_product_candidate(
            db,
            row,
            published_by=payload.published_by,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@router.patch("/product-candidates/{candidate_id}/archive")
def archive_product_candidate(
    candidate_id: int,
    payload: ArchiveCandidateRequest | None = None,
    db: Session = Depends(get_db),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or ArchiveCandidateRequest()
    now = datetime.now(timezone.utc)
    reason = _clean_text(payload.reason) or "Archived from Curator Studio"

    archived_product_id = row.promoted_product_id
    product_was_deactivated = False

    if archived_product_id:
        product = db.query(Product).filter(Product.id == archived_product_id).first()
        if product:
            product.is_active = False
            product.deactivated_at = now
            product.deactivation_reason = reason
            product.availability_status = "archived"
            product.price_check_status = "curator_archive"
            product_was_deactivated = True

    row.review_status = "archived"
    row.reviewed_by = payload.archived_by
    row.reviewed_at = now
    row.review_notes = reason
    row.rejection_reason = None

    db.commit()

    return {
        "status": "ok",
        "candidate_id": row.id,
        "review_status": row.review_status,
        "promoted_product_id": archived_product_id,
        "product_was_deactivated": product_was_deactivated,
    }


@router.patch("/product-candidates/{candidate_id}/restore")
def restore_product_candidate(
    candidate_id: int,
    payload: RestoreCandidateRequest | None = None,
    db: Session = Depends(get_db),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or RestoreCandidateRequest()
    restore_to = (_clean_text(payload.restore_to) or "pending").lower().replace("-", "_")
    if restore_to not in {"pending", "live"}:
        raise HTTPException(status_code=400, detail="restore_to must be 'pending' or 'live'")

    now = datetime.now(timezone.utc)
    restored_product_id = row.promoted_product_id
    product_was_reactivated = False

    if restore_to == "live":
        if not restored_product_id:
            raise HTTPException(status_code=400, detail="Only previously published candidates can be restored live")

        product = db.query(Product).filter(Product.id == restored_product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Promoted product was not found")

        product.is_active = True
        product.deactivated_at = None
        product.deactivation_reason = None
        product.availability_status = "in_stock"
        product.price_check_status = "curator_restore"
        row.review_status = "approved"
        row.promoted_at = row.promoted_at or now
        product_was_reactivated = True
    else:
        row.review_status = "pending"

    row.reviewed_by = payload.restored_by
    row.reviewed_at = now
    row.review_notes = "Restored from archive"
    row.rejection_reason = None

    db.commit()

    return {
        "status": "ok",
        "candidate_id": row.id,
        "review_status": row.review_status,
        "promoted_product_id": restored_product_id,
        "product_was_reactivated": product_was_reactivated,
    }


@router.patch("/product-candidates/{candidate_id}/approve")
def approve_product_candidate(
    candidate_id: int,
    payload: ReviewCandidateRequest | None = None,
    db: Session = Depends(get_db),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    payload = payload or ReviewCandidateRequest()
    row.review_status = "approved"
    row.reviewed_by = payload.reviewed_by
    row.reviewed_at = datetime.now(timezone.utc)
    row.rejection_reason = None

    db.commit()
    return {"status": "ok", "candidate_id": row.id, "review_status": row.review_status}


@router.patch("/product-candidates/{candidate_id}/reject")
def reject_product_candidate(
    candidate_id: int,
    payload: ReviewCandidateRequest,
    db: Session = Depends(get_db),
):
    row = db.query(ProductCandidate).filter(ProductCandidate.id == candidate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not payload.reason or len(payload.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Rejection reason must be at least 3 characters")

    row.review_status = "rejected"
    row.reviewed_by = payload.reviewed_by
    row.reviewed_at = datetime.now(timezone.utc)
    row.rejection_reason = payload.reason.strip()

    db.commit()
    return {"status": "ok", "candidate_id": row.id, "review_status": row.review_status}

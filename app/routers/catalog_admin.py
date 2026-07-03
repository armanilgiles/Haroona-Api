from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AwinProductNormalized, Brand, CatalogBrandControl, City, Product, ProductCandidate
from app.curation.product_candidate_publisher import (
    publish_approved_product_candidates,
    publish_product_candidate,
)
from app.curation.scanner_registry import detect_curation_scanner
from app.curation.shopify_collection import CollectionScanOptions

router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])


class CollectionScanRequest(BaseModel):
    source_url: str = Field(..., min_length=8)
    merchant_name: str = Field("Nobody's Child", min_length=2)
    target_city_slug: str = Field("london", min_length=2)
    normalized_category: str | None = None
    source: str = Field("shopify", min_length=2)
    source_type: str = Field("collection", min_length=2)
    limit: int = Field(30, ge=1, le=100)


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
    }


@router.get("/brand-assets")
def list_brand_assets(
    target_city_slug: str | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
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
            },
        )
        group["candidate_count"] += 1
        if group["latest_candidate_id"] is None or row.id > group["latest_candidate_id"]:
            group["latest_candidate_id"] = row.id
            group["latest_candidate_title"] = row.title
            group["latest_source_url"] = row.source_url

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
        ),
    }


@router.post("/collection-scan")
def scan_collection(
    payload: CollectionScanRequest,
    db: Session = Depends(get_db),
):
    try:
        scanner = detect_curation_scanner(payload.source_url)
        options = CollectionScanOptions(
            source_url=payload.source_url,
            merchant_name=payload.merchant_name,
            target_city_slug=payload.target_city_slug,
            normalized_category=payload.normalized_category,
            source=scanner.source,
            source_type=scanner.source_type,
            limit=payload.limit,
        )

        result = scanner.scan(db, options)
        return {
            **result,
            "scanner": scanner.name,
            "detected_source": scanner.source,
            "detected_source_type": scanner.source_type,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Collection scan failed: {exc}") from exc


@router.get("/product-candidates")
def list_product_candidates(
    status: str | None = Query("pending"),
    source: str | None = Query(None),
    target_city_slug: str | None = Query(None),
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

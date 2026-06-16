from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AwinProductNormalized, CatalogBrandControl, ProductCandidate
from app.curation.shopify_collection import CollectionScanOptions, scan_and_save_shopify_collection

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

@router.post("/collection-scan")
def scan_collection(
    payload: CollectionScanRequest,
    db: Session = Depends(get_db),
):
    try:
        options = CollectionScanOptions(
            source_url=payload.source_url,
            merchant_name=payload.merchant_name,
            target_city_slug=payload.target_city_slug,
            normalized_category=payload.normalized_category,
            source=payload.source,
            source_type=payload.source_type,
            limit=payload.limit,
        )
        return scan_and_save_shopify_collection(db, options)
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

    if status:
        query = query.filter(ProductCandidate.review_status == status)
    if source:
        query = query.filter(ProductCandidate.source == source)
    if target_city_slug:
        query = query.filter(ProductCandidate.target_city_slug == target_city_slug)

    rows = query.offset(offset).limit(limit).all()

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
                "haroona_score": row.haroona_score,
                "score_reasons": row.score_reasons,
                "review_status": row.review_status,
                "review_notes": row.review_notes,
                "rejection_reason": row.rejection_reason,
                "promoted_product_id": row.promoted_product_id,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "count": len(rows),
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

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AwinProductNormalized, CatalogBrandControl

router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])


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
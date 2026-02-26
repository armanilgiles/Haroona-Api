from typing import List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Brand, Country
from app.schemas import BrandOut, BrandLogoIn

router = APIRouter(prefix="/brands", tags=["brands"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=List[BrandOut])
def get_brands(
    country: str | None = Query(None, description="ISO country code, e.g. BR"),
    db: Session = Depends(get_db),
):
    query = db.query(Brand).join(Country)

    if country:
        query = query.filter(Country.code == country.upper())

    return query.order_by(Brand.name).all()


@router.patch("/{brand_id}/logo", response_model=BrandOut)
def set_brand_logo(
    brand_id: int,
    payload: BrandLogoIn,
    db: Session = Depends(get_db),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    brand.logo_url = payload.logo_url
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand
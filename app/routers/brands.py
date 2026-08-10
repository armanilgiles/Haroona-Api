from typing import List

from fastapi import APIRouter, Depends, Query, HTTPException, Request, Response
from sqlalchemy.orm import Session, contains_eager

from app.database import get_db
from app.http_cache import apply_conditional_cache
from app.models import Brand, Country
from app.schemas import BrandCountry, BrandOut, BrandLogoIn

router = APIRouter(prefix="/brands", tags=["brands"])

@router.get("", response_model=List[BrandOut])
def get_brands(
    request: Request,
    response: Response,
    country: str | None = Query(None, description="ISO country code, e.g. BR"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Brand)
        .join(Country, Brand.country_id == Country.id)
        .options(contains_eager(Brand.country))
    )

    if country:
        query = query.filter(Country.code == country.upper())

    brands = query.order_by(Brand.name).all()
    payload = [
        BrandOut(
            id=brand.id,
            name=brand.name,
            country=BrandCountry(
                code=brand.country.code,
                name=brand.country.name,
            ),
            logoUrl=brand.logo_url,
        )
        for brand in brands
    ]
    not_modified = apply_conditional_cache(
        request=request,
        response=response,
        payload=payload,
    )
    return not_modified or payload


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

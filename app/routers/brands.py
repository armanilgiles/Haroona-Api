from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Brand, Country
from app.schemas import BrandOut

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
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Product, Brand
from app.schemas import ProductOut

router = APIRouter(prefix="/products", tags=["products"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=List[ProductOut])
def get_products(
    brand_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Product).join(Brand)

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    return query.order_by(Product.id.desc()).limit(50).all()

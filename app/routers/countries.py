from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Country
from app.schemas import CountryOut

router = APIRouter(prefix="/countries", tags=["countries"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=List[CountryOut])
def get_countries(db: Session = Depends(get_db)):
    return (
        db.query(Country)
        .order_by(Country.name)
        .all()
    )

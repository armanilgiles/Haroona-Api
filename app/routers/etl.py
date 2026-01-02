from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.etl.rakuten_service import run_rakuten_etl

router = APIRouter(prefix="/etl", tags=["etl"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/rakuten")
def run_rakuten(db: Session = Depends(get_db)):
    return run_rakuten_etl(db)

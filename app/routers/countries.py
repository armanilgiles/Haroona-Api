from typing import List
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.http_cache import apply_conditional_cache
from app.models import Country
from app.schemas import CountryOut

router = APIRouter(prefix="/countries", tags=["countries"])

@router.get("", response_model=List[CountryOut])
def get_countries(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    countries = (
        db.query(Country)
        .order_by(Country.name)
        .all()
    )
    payload = [
        CountryOut(id=country.id, code=country.code, name=country.name)
        for country in countries
    ]
    not_modified = apply_conditional_cache(
        request=request,
        response=response,
        payload=payload,
    )
    return not_modified or payload

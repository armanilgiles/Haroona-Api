from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session, contains_eager

from app.database import get_db
from app.http_cache import apply_conditional_cache
from app.models import City, Country
from app.schemas import CityOut

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("", response_model=list[CityOut])
def get_cities(
    request: Request,
    response: Response,
    country_code: str | None = Query(None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
):
    query = (
        db.query(City)
        .join(Country, City.country_id == Country.id)
        .options(contains_eager(City.country))
    )

    if country_code:
        query = query.filter(Country.code == country_code.upper())

    cities = query.order_by(City.name.asc()).all()

    payload = [
        CityOut(
            id=city.id,
            slug=city.slug,
            name=city.name,
            countryCode=city.country.code,
            countryName=city.country.name,
            latitude=float(city.latitude),
            longitude=float(city.longitude),
            markerColor=city.marker_color,
            imageUrl=city.image_url,
            followers=city.followers,
        )
        for city in cities
    ]
    not_modified = apply_conditional_cache(
        request=request,
        response=response,
        payload=payload,
    )
    return not_modified or payload

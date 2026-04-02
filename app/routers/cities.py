from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import City, Country
from app.schemas import CityOut

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("", response_model=list[CityOut])
def get_cities(
    country_code: str | None = Query(None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
):
    query = db.query(City).join(Country)

    if country_code:
        query = query.filter(Country.code == country_code.upper())

    cities = query.order_by(City.name.asc()).all()

    return [
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

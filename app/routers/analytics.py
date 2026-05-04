from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalyticsEvent
from app.schemas import AnalyticsEventCreate, AnalyticsEventOut


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/events",
    response_model=AnalyticsEventOut,
    status_code=status.HTTP_201_CREATED,
)
def create_analytics_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    event = AnalyticsEvent(
        event_name=payload.eventName,
        anonymous_id=payload.anonymousId,
        session_id=payload.sessionId,
        product_id=payload.productId,
        db_product_id=payload.dbProductId,
        city_slug=payload.citySlug,
        city_name=payload.cityName,
        path=payload.path,
        referrer=payload.referrer,
        user_agent=request.headers.get("user-agent"),
        properties=payload.properties or {},
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return AnalyticsEventOut(ok=True, id=event.id)

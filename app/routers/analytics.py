from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.database import get_db
from app.models import AnalyticsEvent, Brand, City, Product, User
from app.schemas import AnalyticsEventCreate, AnalyticsEventOut


router = APIRouter(prefix="/analytics", tags=["analytics"])

CITY_CLICK_EVENTS = ("city_click", "city_select", "city_selected")
PRODUCT_CLICK_EVENTS = ("product_click", "product_card_click", "product_view")
HANDOFF_EVENTS = (
    "handoff_start",
    "handoff_redirect",
    "affiliate_click",
    "product_handoff",
)
SAVE_EVENTS = ("saved_find", "save_product", "product_save")


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


@router.get("/admin/summary")
def get_analytics_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return real Haroona analytics numbers for the private admin dashboard."""

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)

    base_filters = [AnalyticsEvent.created_at >= start]
    previous_filters = [
        AnalyticsEvent.created_at >= previous_start,
        AnalyticsEvent.created_at < start,
    ]

    current_counts = _get_kpi_counts(db, base_filters)
    previous_counts = _get_kpi_counts(db, previous_filters)

    return {
        "range": {
            "days": days,
            "from": start.isoformat(),
            "to": now.isoformat(),
        },
        "kpis": _build_kpis(current_counts, previous_counts),
        "timeline": _get_timeline(db, start.date(), now.date()),
        "topCities": _get_top_cities(db, base_filters),
        "topProducts": _get_top_products(db, base_filters),
        "trafficSources": _get_traffic_sources(db, base_filters),
        "eventBreakdown": _get_event_breakdown(db, base_filters),
        "recentEvents": _get_recent_events(db, base_filters),
    }


def _get_kpi_counts(db: Session, filters: list):
    visitor_key = func.coalesce(AnalyticsEvent.anonymous_id, AnalyticsEvent.session_id)

    row = (
        db.query(
            func.count(AnalyticsEvent.id).label("total_events"),
            func.count(func.distinct(visitor_key)).label("total_visitors"),
            func.count(func.distinct(AnalyticsEvent.session_id)).label("total_sessions"),
            func.coalesce(
                func.sum(
                    case((AnalyticsEvent.event_name.in_(CITY_CLICK_EVENTS), 1), else_=0)
                ),
                0,
            ).label("city_clicks"),
            func.coalesce(
                func.sum(
                    case((AnalyticsEvent.event_name.in_(PRODUCT_CLICK_EVENTS), 1), else_=0)
                ),
                0,
            ).label("product_clicks"),
            func.coalesce(
                func.sum(case((AnalyticsEvent.event_name.in_(HANDOFF_EVENTS), 1), else_=0)),
                0,
            ).label("handoffs"),
            func.coalesce(
                func.sum(case((AnalyticsEvent.event_name.in_(SAVE_EVENTS), 1), else_=0)),
                0,
            ).label("saved_finds"),
        )
        .filter(*filters)
        .one()
    )

    product_clicks = int(row.product_clicks or 0)
    handoffs = int(row.handoffs or 0)

    return {
        "totalEvents": int(row.total_events or 0),
        "totalVisitors": int(row.total_visitors or 0),
        "totalSessions": int(row.total_sessions or 0),
        "cityClicks": int(row.city_clicks or 0),
        "productClicks": product_clicks,
        "handoffs": handoffs,
        "savedFinds": int(row.saved_finds or 0),
        "handoffRate": round((handoffs / product_clicks) * 100, 2)
        if product_clicks
        else 0,
    }


def _build_kpis(current: dict, previous: dict):
    keys = [
        "totalVisitors",
        "totalSessions",
        "cityClicks",
        "productClicks",
        "handoffs",
        "savedFinds",
        "handoffRate",
        "totalEvents",
    ]

    return {
        key: {
            "value": current[key],
            "previousValue": previous[key],
            "changePercent": _percent_change(current[key], previous[key]),
        }
        for key in keys
    }


def _get_timeline(db: Session, start_date: date, end_date: date):
    visitor_key = func.coalesce(AnalyticsEvent.anonymous_id, AnalyticsEvent.session_id)
    bucket = cast(AnalyticsEvent.created_at, Date).label("bucket")

    rows = (
        db.query(
            bucket,
            func.count(AnalyticsEvent.id).label("events"),
            func.count(func.distinct(visitor_key)).label("visitors"),
            func.count(func.distinct(AnalyticsEvent.session_id)).label("sessions"),
            func.coalesce(
                func.sum(
                    case((AnalyticsEvent.event_name.in_(CITY_CLICK_EVENTS), 1), else_=0)
                ),
                0,
            ).label("city_clicks"),
            func.coalesce(
                func.sum(
                    case((AnalyticsEvent.event_name.in_(PRODUCT_CLICK_EVENTS), 1), else_=0)
                ),
                0,
            ).label("product_clicks"),
            func.coalesce(
                func.sum(case((AnalyticsEvent.event_name.in_(HANDOFF_EVENTS), 1), else_=0)),
                0,
            ).label("handoffs"),
            func.coalesce(
                func.sum(case((AnalyticsEvent.event_name.in_(SAVE_EVENTS), 1), else_=0)),
                0,
            ).label("saved_finds"),
        )
        .filter(
            AnalyticsEvent.created_at
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        )
        .group_by(bucket)
        .order_by(bucket)
        .all()
    )

    rows_by_date = {row.bucket.isoformat(): row for row in rows}
    timeline = []
    cursor = start_date

    while cursor <= end_date:
        key = cursor.isoformat()
        row = rows_by_date.get(key)
        timeline.append(
            {
                "date": key,
                "events": int(row.events or 0) if row else 0,
                "visitors": int(row.visitors or 0) if row else 0,
                "sessions": int(row.sessions or 0) if row else 0,
                "cityClicks": int(row.city_clicks or 0) if row else 0,
                "productClicks": int(row.product_clicks or 0) if row else 0,
                "handoffs": int(row.handoffs or 0) if row else 0,
                "savedFinds": int(row.saved_finds or 0) if row else 0,
            }
        )
        cursor += timedelta(days=1)

    return timeline


def _get_top_cities(db: Session, filters: list, limit: int = 10):
    visitor_key = func.coalesce(AnalyticsEvent.anonymous_id, AnalyticsEvent.session_id)

    clicks = func.count(AnalyticsEvent.id).label("clicks")

    rows = (
        db.query(
            AnalyticsEvent.city_slug.label("city_slug"),
            AnalyticsEvent.city_name.label("city_name"),
            clicks,
            func.count(func.distinct(visitor_key)).label("visitors"),
            func.count(func.distinct(AnalyticsEvent.session_id)).label("sessions"),
        )
        .filter(*filters)
        .filter(AnalyticsEvent.event_name.in_(CITY_CLICK_EVENTS))
        .filter(AnalyticsEvent.city_slug.isnot(None))
        .group_by(AnalyticsEvent.city_slug, AnalyticsEvent.city_name)
        .order_by(clicks.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "citySlug": row.city_slug,
            "cityName": row.city_name,
            "clicks": int(row.clicks or 0),
            "visitors": int(row.visitors or 0),
            "sessions": int(row.sessions or 0),
        }
        for row in rows
    ]


def _get_top_products(db: Session, filters: list, limit: int = 10):
    product_clicks = func.coalesce(
        func.sum(case((AnalyticsEvent.event_name.in_(PRODUCT_CLICK_EVENTS), 1), else_=0)),
        0,
    ).label("product_clicks")
    handoffs = func.coalesce(
        func.sum(case((AnalyticsEvent.event_name.in_(HANDOFF_EVENTS), 1), else_=0)),
        0,
    ).label("handoffs")
    total_events = func.count(AnalyticsEvent.id).label("total_events")

    rows = (
        db.query(
            AnalyticsEvent.product_id.label("product_id"),
            AnalyticsEvent.db_product_id.label("db_product_id"),
            Product.name.label("product_name"),
            Product.product_image_url.label("image_url"),
            Product.affiliate_url.label("affiliate_url"),
            Brand.name.label("brand_name"),
            City.slug.label("city_slug"),
            City.name.label("city_name"),
            product_clicks,
            handoffs,
            total_events,
        )
        .outerjoin(Product, AnalyticsEvent.db_product_id == Product.id)
        .outerjoin(Brand, Product.brand_id == Brand.id)
        .outerjoin(City, Product.city_id == City.id)
        .filter(*filters)
        .filter(AnalyticsEvent.event_name.in_(PRODUCT_CLICK_EVENTS + HANDOFF_EVENTS))
        .filter(
            (AnalyticsEvent.product_id.isnot(None))
            | (AnalyticsEvent.db_product_id.isnot(None))
        )
        .group_by(
            AnalyticsEvent.product_id,
            AnalyticsEvent.db_product_id,
            Product.name,
            Product.product_image_url,
            Product.affiliate_url,
            Brand.name,
            City.slug,
            City.name,
        )
        .order_by(total_events.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "productId": row.product_id,
            "dbProductId": row.db_product_id,
            "productName": row.product_name,
            "brandName": row.brand_name,
            "citySlug": row.city_slug,
            "cityName": row.city_name,
            "imageUrl": row.image_url,
            "affiliateUrl": row.affiliate_url,
            "productClicks": int(row.product_clicks or 0),
            "handoffs": int(row.handoffs or 0),
            "totalEvents": int(row.total_events or 0),
        }
        for row in rows
    ]


def _get_traffic_sources(db: Session, filters: list, limit: int = 8):
    events = func.count(AnalyticsEvent.id).label("events")

    rows = (
        db.query(
            AnalyticsEvent.referrer.label("referrer"),
            events,
            func.count(func.distinct(AnalyticsEvent.session_id)).label("sessions"),
        )
        .filter(*filters)
        .group_by(AnalyticsEvent.referrer)
        .order_by(events.desc())
        .limit(100)
        .all()
    )

    sources: dict[str, dict] = {}

    for row in rows:
        source = _source_label(row.referrer)
        existing = sources.setdefault(
            source,
            {
                "source": source,
                "events": 0,
                "sessions": 0,
            },
        )
        existing["events"] += int(row.events or 0)
        existing["sessions"] += int(row.sessions or 0)

    return sorted(sources.values(), key=lambda item: item["events"], reverse=True)[:limit]


def _get_event_breakdown(db: Session, filters: list):
    event_count = func.count(AnalyticsEvent.id).label("event_count")

    rows = (
        db.query(
            AnalyticsEvent.event_name.label("event_name"),
            event_count,
        )
        .filter(*filters)
        .group_by(AnalyticsEvent.event_name)
        .order_by(event_count.desc())
        .all()
    )

    return [
        {"eventName": row.event_name, "count": int(row.event_count or 0)}
        for row in rows
    ]


def _get_recent_events(db: Session, filters: list, limit: int = 25):
    rows = (
        db.query(AnalyticsEvent)
        .filter(*filters)
        .order_by(AnalyticsEvent.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": row.id,
            "eventName": row.event_name,
            "anonymousId": row.anonymous_id,
            "sessionId": row.session_id,
            "productId": row.product_id,
            "dbProductId": row.db_product_id,
            "citySlug": row.city_slug,
            "cityName": row.city_name,
            "path": row.path,
            "referrer": row.referrer,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _source_label(referrer: str | None) -> str:
    if not referrer:
        return "Direct / unknown"

    hostname = urlparse(referrer).hostname or referrer
    hostname = hostname.lower().replace("www.", "")

    if "instagram" in hostname:
        return "Instagram"
    if "pinterest" in hostname:
        return "Pinterest"
    if "google" in hostname:
        return "Google"
    if "tiktok" in hostname:
        return "TikTok"
    if "facebook" in hostname or hostname == "fb.com":
        return "Facebook"
    if "haroona" in hostname or "vercel.app" in hostname:
        return "Haroona"

    return hostname


def _percent_change(current: int | float, previous: int | float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0

    return round(((current - previous) / previous) * 100, 2)

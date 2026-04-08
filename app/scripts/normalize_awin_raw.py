from __future__ import annotations

import re
import sys
from decimal import Decimal, InvalidOperation

from app.database import SessionLocal
from app.models import AwinProductFeedRaw, AwinProductNormalized


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def normalize_brand_name(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    return value.title()


def parse_price(raw_price: str | None) -> tuple[Decimal | None, str | None]:
    raw_price = clean_text(raw_price)
    if not raw_price:
        return None, None

    match = re.match(r"^\s*([0-9]+(?:\.[0-9]{1,2})?)\s+([A-Z]{3})\s*$", raw_price)
    if not match:
        return None, None

    amount_str, currency = match.groups()

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        return None, None

    return amount, currency


def map_normalized_category(
    title: str | None,
    product_type: str | None,
    google_product_category: str | None,
) -> str | None:
    haystack = " ".join(
        [
            clean_text(title) or "",
            clean_text(product_type) or "",
            clean_text(google_product_category) or "",
        ]
    ).lower()

    category_rules: list[tuple[list[str], str]] = [
        (["dress"], "dress"),
        (["earring", "necklace", "bracelet", "ring", "jewelry", "jewellery"], "jewelry"),
        (["sunglasses", "glasses", "eyewear"], "eyewear"),
        (["bag", "tote", "purse", "wallet", "crossbody", "clutch"], "bags"),
        (["shoe", "sneaker", "boot", "heel", "loafer", "sandal", "flat"], "shoes"),
        (["skirt"], "skirt"),
        (["pant", "trouser", "legging", "jean", "denim"], "bottoms"),
        (["shirt", "blouse", "top", "tee", "tank", "sweater", "cardigan", "hoodie"], "tops"),
        (["sock"], "socks"),
        (["scrunchie", "headband", "hair clip", "barrette", "hair accessory"], "hair-accessories"),
        (["coat", "jacket", "blazer"], "outerwear"),
        (["hat", "cap", "beanie"], "headwear"),
        (["swim", "bikini", "one-piece"], "swimwear"),
        (["scarf"], "scarves"),
    ]

    for keywords, normalized in category_rules:
        if any(keyword in haystack for keyword in keywords):
            return normalized

    return None


def build_review_notes(
    raw: AwinProductFeedRaw,
    price_amount,
    currency,
    normalized_category,
    affiliate_url,
    image_url,
) -> str | None:
    notes: list[str] = []

    availability = (raw.availability or "").strip().lower()
    if availability and availability != "in_stock":
        notes.append(f"availability={raw.availability}")

    if not raw.brand:
        notes.append("missing brand")

    if not normalized_category:
        notes.append("unknown category")

    if price_amount is None or not currency:
        notes.append("unparseable price")

    if not affiliate_url:
        notes.append("missing affiliate url")

    if not image_url:
        notes.append("missing image")

    return "; ".join(notes) or None


def normalize_awin_raw(limit: int | None = None) -> dict:
    db = SessionLocal()
    created = 0
    skipped = 0

    try:
        query = db.query(AwinProductFeedRaw).order_by(AwinProductFeedRaw.id.asc())
        if limit is not None:
            query = query.limit(limit)

        raw_rows = query.all()

        for raw in raw_rows:
            existing = (
                db.query(AwinProductNormalized)
                .filter(AwinProductNormalized.raw_id == raw.id)
                .first()
            )
            if existing:
                skipped += 1
                continue

            chosen_price_raw = raw.sale_price_raw or raw.price_raw
            price_amount, currency = parse_price(chosen_price_raw)

            affiliate_url = clean_text(raw.aw_deep_link)
            merchant_url = clean_text(raw.link)
            image_url = clean_text(raw.image_link)
            brand_name = normalize_brand_name(raw.brand or raw.advertiser_name)
            normalized_category = map_normalized_category(
                raw.title,
                raw.product_type,
                raw.google_product_category,
            )

            availability = clean_text(raw.availability)
            availability_lc = (availability or "").lower()

            is_usable = all(
                [
                    clean_text(raw.title),
                    affiliate_url,
                    image_url,
                    price_amount is not None,
                    currency,
                    availability_lc == "in_stock",
                ]
            )

            review_notes = build_review_notes(
                raw=raw,
                price_amount=price_amount,
                currency=currency,
                normalized_category=normalized_category,
                affiliate_url=affiliate_url,
                image_url=image_url,
            )

            needs_review = (not is_usable) or (normalized_category is None)
            review_status = "pending"
            if is_usable and not needs_review:
                review_status = "approved"

            record = AwinProductNormalized(
                raw_id=raw.id,
                source="awin",
                external_product_id=raw.external_product_id,
                advertiser_id=raw.advertiser_id,
                advertiser_name=raw.advertiser_name,
                title=clean_text(raw.title) or "Untitled",
                description=clean_text(raw.description),
                brand_name=brand_name,
                price_amount=price_amount,
                currency=currency,
                affiliate_url=affiliate_url,
                merchant_url=merchant_url,
                image_url=image_url,
                availability=availability,
                google_product_category=clean_text(raw.google_product_category),
                product_type=clean_text(raw.product_type),
                normalized_category=normalized_category,
                is_usable=is_usable,
                needs_review=needs_review,
                review_status=review_status,
                review_notes=review_notes,
            )

            db.add(record)
            created += 1

        db.commit()

        usable_count = db.query(AwinProductNormalized).filter(
            AwinProductNormalized.is_usable.is_(True)
        ).count()

        return {
            "status": "ok",
            "created": created,
            "skipped": skipped,
            "usable_total": usable_count,
        }
    finally:
        db.close()


if __name__ == "__main__":
    limit = None

    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python -m app.scripts.normalize_awin_raw [limit]")

    result = normalize_awin_raw(limit=limit)
    print(result)
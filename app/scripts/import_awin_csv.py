from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from app.database import SessionLocal
from app.models import AwinProductFeedRaw


KEEP_EMPTY_AS_NONE = {
    "advertiser_id",
    "advertiser_name",
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "additional_image_link",
    "aw_deep_link",
    "google_product_category",
    "product_type",
    "brand",
    "availability",
    "condition",
    "price",
    "sale_price",
}


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def import_awin_csv(csv_path: str) -> dict:
    file_path = Path(csv_path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    db = SessionLocal()
    inserted = 0
    skipped = 0

    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)

            for row in reader:
                external_product_id = clean_value(row.get("id"))
                title = clean_value(row.get("title"))

                if not external_product_id or not title:
                    skipped += 1
                    continue

                exists = (
                    db.query(AwinProductFeedRaw)
                    .filter(AwinProductFeedRaw.source_file == file_path.name)
                    .filter(AwinProductFeedRaw.external_product_id == external_product_id)
                    .first()
                )
                if exists:
                    skipped += 1
                    continue

                normalized_row = {
                    key: (clean_value(value) if key in KEEP_EMPTY_AS_NONE else value)
                    for key, value in row.items()
                }

                record = AwinProductFeedRaw(
                    source_file=file_path.name,
                    advertiser_id=clean_value(row.get("advertiser_id")),
                    advertiser_name=clean_value(row.get("advertiser_name")),
                    external_product_id=external_product_id,
                    title=title,
                    description=clean_value(row.get("description")),
                    brand=clean_value(row.get("brand")),
                    google_product_category=clean_value(row.get("google_product_category")),
                    product_type=clean_value(row.get("product_type")),
                    availability=clean_value(row.get("availability")),
                    condition=clean_value(row.get("condition")),
                    price_raw=clean_value(row.get("price")),
                    sale_price_raw=clean_value(row.get("sale_price")),
                    link=clean_value(row.get("link")),
                    aw_deep_link=clean_value(row.get("aw_deep_link")),
                    image_link=clean_value(row.get("image_link")),
                    additional_image_link=clean_value(row.get("additional_image_link")),
                    raw_payload=json.dumps(normalized_row, ensure_ascii=False),
                )
                db.add(record)
                inserted += 1

            db.commit()

        return {
            "status": "ok",
            "file": file_path.name,
            "inserted": inserted,
            "skipped": skipped,
        }
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m app.scripts.import_awin_csv /absolute/or/relative/path/to/file.csv")

    result = import_awin_csv(sys.argv[1])
    print(result)
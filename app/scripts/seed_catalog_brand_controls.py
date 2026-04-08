from __future__ import annotations

from app.database import SessionLocal
from app.data.brand_map import BRAND_MAP
from app.models import CatalogBrandControl


DISPLAY_NAMES = {
    "nike": "Nike",
    "adidas": "Adidas",
    "mure_and_grand": "Mure + Grand",
    "mulberry_and_grand": "Mulberry + Grand",
    "patches_and_pins": "Patches + Pins",
    "dipped_shop": "Dipped Shop",
    "urban_expressions": "Urban Expressions",
    "shiraleah": "Shiraleah",
}


def seed_catalog_brand_controls() -> dict:
    db = SessionLocal()
    created = 0
    updated = 0

    try:
        for brand_key, meta in BRAND_MAP.items():
            row = (
                db.query(CatalogBrandControl)
                .filter(CatalogBrandControl.source == "awin")
                .filter(CatalogBrandControl.brand_key == brand_key)
                .first()
            )

            display_name = meta.get("display_name") or DISPLAY_NAMES.get(brand_key) or brand_key.replace("_", " ").title()
            origin_country_code = meta["origin_country"]

            if row:
                row.display_name = display_name
                row.origin_country_code = origin_country_code
                row.is_allowed = True
                updated += 1
            else:
                db.add(
                    CatalogBrandControl(
                        source="awin",
                        brand_key=brand_key,
                        display_name=display_name,
                        origin_country_code=origin_country_code,
                        is_allowed=True,
                        notes=None,
                    )
                )
                created += 1

        db.commit()
        return {"status": "ok", "created": created, "updated": updated}
    finally:
        db.close()


if __name__ == "__main__":
    print(seed_catalog_brand_controls())
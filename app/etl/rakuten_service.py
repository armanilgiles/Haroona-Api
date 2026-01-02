from sqlalchemy.orm import Session

from app.etl.rakuten_mock import MOCK_RAKUTEN_PRODUCTS
from app.etl.rakuten_transform import transform_rakuten_products
from app.models import Brand, Product

def run_rakuten_etl(db: Session) -> dict:
    brands = db.query(Brand).all()
    brand_map = {b.name: b for b in brands}

    products = transform_rakuten_products(
        MOCK_RAKUTEN_PRODUCTS,
        brand_map,
    )

    inserted = 0
    for p in products:
        exists = (
            db.query(Product)
            .filter_by(external_id=p.external_id, source=p.source)
            .first()
        )
        if exists:
            continue

        db.add(p)
        inserted += 1

    db.commit()

    return {
        "source": "rakuten",
        "inserted": inserted,
        "skipped": len(products) - inserted,
    }

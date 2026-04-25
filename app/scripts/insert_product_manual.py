import re
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Product, Brand, City


def extract_product_id(url: str) -> str:
    match = re.search(r'-(\d+)', url)
    if not match:
        raise ValueError("Could not extract product ID from URL")
    return match.group(1)


def get_or_raise_brand(db: Session, name: str):
    brand = db.query(Brand).filter(Brand.name.ilike(f"%{name}%")).first()
    if not brand:
        raise ValueError(f"Brand '{name}' not found")
    return brand


def get_or_raise_city(db: Session, name: str):
    city = db.query(City).filter(City.name == name).first()
    if not city:
        raise ValueError(f"City '{name}' not found")
    return city


def insert_product_manual(
    url: str,
    price: float,
    brand_name: str,
    city_name: str,
    category: str,
    vibe: str,
    name: str,
):
    db: Session = SessionLocal()

    try:
        product_id = extract_product_id(url)

        external_id = f"{brand_name.lower().replace(' ', '')}-{product_id}"

        brand = get_or_raise_brand(db, brand_name)
        city = get_or_raise_city(db, city_name)

        product = Product(
            name=name,
            brand_id=brand.id,
            price=price,
            currency="USD",
            affiliate_url=url,
            city_id=city.id,
            category=category,
            vibe=vibe,
            external_id=external_id,
            source="manual",
            is_active=True,
        )

        db.add(product)
        db.commit()
        db.refresh(product)

        print(f"✅ Inserted: {product.name}")
        print(f"External ID: {external_id}")

    except Exception as e:
        db.rollback()
        print("❌ Error:", e)

    finally:
        db.close()
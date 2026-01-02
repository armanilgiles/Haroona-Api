
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI,Query,Depends
from app.routers import etl
from app.utils.normalize import normalize_brand
from app.data.brand_map import BRAND_MAP
from app.etl.transform import transform_products
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal, engine
from app.models import Country, Brand,Base
from app.models import Base, Country, Brand
from app.routers import health, countries, brands
from app.routers import health, countries, brands, products
from app.api.etl import router as etl_router
from app.routers import auth
from app.auth.dependencies import get_current_user
from fastapi.middleware.cors import CORSMiddleware




Base.metadata.create_all(bind=engine)




app = FastAPI(title="MapMyStyle API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://mapmystyle.com",

    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(etl.router)
app.include_router(etl_router)
app.include_router(health.router)
app.include_router(countries.router)
app.include_router(brands.router)
app.include_router(products.router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/me")
def me(user=Depends(get_current_user)):
    return user


@app.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "postgres connected"}


@app.get("/")
def hello_world():
    return {"message": "Hello World"}

@app.get("/brands/by-id/{brand_id}")
def get_brand_by_id(brand_id: str):
    for key, brand in BRAND_MAP.items():
        if brand["id"] == brand_id:
            return {
                "key": key,
                **brand
            }

    return {"error": "Brand not found"}

@app.get("/brands/search")
def search_brands(q: str = Query(..., min_length=1)):
    normalized_query, confidence = normalize_brand(q)

    results = []

    for brand_key, brand in BRAND_MAP.items():
        # exact or alias match
        if brand_key == normalized_query:
            results.append({
                "key": brand_key,
                "confidence": confidence,
                **brand
            })
            continue

        # partial match (search UX)
        if normalized_query in brand_key:
            results.append({
                "key": brand_key,
                "confidence": "partial",
                **brand
            })

    return {
        "query": q,
        "normalized_query": normalized_query,
        "results": results
    }



@app.post("/seed")
def seed(db: Session = Depends(get_db)):
    brazil = Country(code="BR", name="Brazil")
    france = Country(code="FR", name="France")

    db.add_all([brazil, france])
    db.commit()

    db.refresh(brazil)
    db.refresh(france)

    db.add_all([
        Brand(name="Osklen", country_id=brazil.id),
        Brand(name="Farm Rio", country_id=brazil.id),
        Brand(name="Jacquemus", country_id=france.id),
    ])

    db.commit()
    return {"status": "seeded"}

# --- Read-only APIs ---

@app.get("/countries")
def get_countries(db: Session = Depends(get_db)):
    countries = (
        db.query(Country)
        .order_by(Country.name)
        .all()
    )

    return [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
        }
        for c in countries
    ]


@app.get("/brands")
def get_brands(
    country: str | None = Query(None, description="ISO country code, e.g. BR"),
    db: Session = Depends(get_db),
):
    query = db.query(Brand).join(Country)

    if country:
        query = query.filter(Country.code == country.upper())

    brands = query.order_by(Brand.name).all()

    return [
        {
            "id": b.id,
            "name": b.name,
            "country": {
                "code": b.country.code,
                "name": b.country.name,
            },
        }
        for b in brands
    ]

@app.get("/brands")
def get_brands():
    return BRAND_MAP

@app.get("/etl/transform")
def run_transform():
    return transform_products(MOCK_PRODUCTS)


MOCK_PRODUCTS = [
    {
        "productId": "123",
        "productName": "Nike Air Max",
        "brandName": "NIKE®",
        "price": "120",
        "currency": "USD",
        "clickUrl": "https://example.com/nike-air-max",
    },
    {
        "productId": "456",
        "productName": "Adidas Ultraboost",
        "brandName": "Adidas Originals",
        "price": "180",
        "currency": "USD",
        "clickUrl": "https://example.com/adidas-ultraboost",
    },
    {
        "productId": "999",
        "productName": "Unknown Shoe",
        "brandName": "RandomBrand",
        "price": "50",
    },
]


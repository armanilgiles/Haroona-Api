from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models import Base
from app.routers import auth, etl, health, countries, brands, products, dev, cities, feed
from app.api.etl import router as etl_router
from app.auth.dependencies import get_current_user
from app.schemas import UserMeOut


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Haroona API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://haroona.com",
        "https://www.haroona.com",
        "https://haroona.com",
        "https://www.haroona.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(etl.router)
app.include_router(etl_router)
app.include_router(health.router)
app.include_router(countries.router)
app.include_router(brands.router)
app.include_router(products.router)
app.include_router(dev.router)
app.include_router(cities.router)
app.include_router(feed.router)


@app.get("/me", response_model=UserMeOut)
def me(user=Depends(get_current_user)):
    return user


@app.post("/me/welcome-seen", response_model=UserMeOut)
def set_welcome_seen(user=Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.welcome_seen:
        user.welcome_seen = True
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@app.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "postgres connected"}


@app.get("/")
def root():
    return {"message": "Haroona API"}

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, HttpUrl, Field


# ----------------------------
# Auth / user
# ----------------------------


class UserMeOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    avatar: HttpUrl | None = None
    welcome_seen: bool

    class Config:
        from_attributes = True


# ----------------------------
# Countries / brands
# ----------------------------


class CountryOut(BaseModel):
    id: int
    code: str
    name: str

    class Config:
        from_attributes = True


class BrandCountry(BaseModel):
    code: str
    name: str

    class Config:
        from_attributes = True


class BrandOut(BaseModel):
    id: int
    name: str
    country: BrandCountry
    # Optional: used by the UI for clickout handoff fallbacks
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class BrandMini(BaseModel):
    id: int
    name: str
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True

class BrandLogoIn(BaseModel):
    # Accepts {"logoUrl": "..."} from the UI
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        allow_population_by_field_name = True


# ----------------------------
# Products
# ----------------------------


class ImageAssetOut(BaseModel):
    url: str
    alt: str
    width: int | None = None
    height: int | None = None


class ProductCardOut(BaseModel):
    """UI-aligned product shape.

    This matches the current Haroona/Aruona UI expectations:
    - productImage is used in the sheet grid card
    - logoImage is used for the logo handoff transition
    """

    # New canonical fields (camelCase to match UI)
    productId: str
    productName: str
    advertiserId: str | None = None
    brandName: str | None = None
    price: str | None = None
    currency: str | None = None
    affiliateUrl: str
    productImage: ImageAssetOut | None = None
    logoImage: ImageAssetOut | None = None

    # Back-compat fields (older UI)
    id: int | None = None
    name: str | None = None
    brand: BrandMini | None = None
    imageUrl: str | None = None
    imageAlt: str | None = None


# Kept for compatibility with older clients/tests.
class ProductOut(BaseModel):
    id: int
    name: str
    price: Decimal | None
    currency: str
    affiliate_url: HttpUrl
    source: str
    brand: BrandMini

    class Config:
        from_attributes = True

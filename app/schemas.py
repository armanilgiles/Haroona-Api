from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, HttpUrl, Field


class UserMeOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    avatar: HttpUrl | None = None
    welcome_seen: bool

    class Config:
        from_attributes = True


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
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        allow_population_by_field_name = True


class ImageAssetOut(BaseModel):
    url: str
    alt: str
    width: int | None = None
    height: int | None = None


class ProductCardOut(BaseModel):
    productId: str
    productName: str
    advertiserId: str | None = None
    brandName: str | None = None
    price: str | None = None
    currency: str | None = None
    affiliateUrl: str
    productImage: ImageAssetOut | None = None
    logoImage: ImageAssetOut | None = None

    id: int | None = None
    name: str | None = None
    brand: BrandMini | None = None
    imageUrl: str | None = None
    imageAlt: str | None = None


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


class CityOut(BaseModel):
    id: int
    slug: str
    name: str
    countryCode: str
    countryName: str
    latitude: float
    longitude: float
    markerColor: str | None = None
    imageUrl: str | None = None
    followers: int


class FeedProductOut(BaseModel):
    productId: str
    productName: str
    advertiserId: str | None
    brandName: str | None
    price: str | None
    currency: str | None
    affiliateUrl: str | None
    productImage: ImageAssetOut | None
    logoImage: ImageAssetOut | None

    videoUrl: str | None = None  # 🔥 THIS FIXES EVERYTHING

    citySlug: str | None
    cityName: str | None
    category: str | None
    style: str | None
    vibe: str | None
    isBestSeller: bool | None

class FeedResponse(BaseModel):
    items: list[FeedProductOut]
    total: int
    selectedCity: str | None = None
    mode: str


class FeedFiltersOut(BaseModel):
    categories: list[str]
    styles: list[str]
    vibes: list[str]

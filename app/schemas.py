from pydantic import BaseModel
from decimal import Decimal
from pydantic import BaseModel, HttpUrl

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

    class Config:
        from_attributes = True


class BrandMini(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


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


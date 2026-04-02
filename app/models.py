from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Numeric, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    avatar = Column(String(500), nullable=True)
    welcome_seen = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User {self.email}>"


class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(2), nullable=False, unique=True)
    name = Column(String(100), nullable=False, unique=True)

    brands = relationship("Brand", back_populates="country")
    cities = relationship("City", back_populates="country")

    def __repr__(self):
        return f"<Country {self.code}>"


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=False)
    logo_url = Column(String(500), nullable=True)

    country = relationship("Country", back_populates="brands")
    products = relationship("Product", back_populates="brand")

    __table_args__ = (
        UniqueConstraint("name", "country_id", name="uq_brand_name_country"),
    )

    def __repr__(self):
        return f"<Brand {self.name}>"


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(80), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=False)

    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)

    marker_color = Column(String(30), nullable=True)
    image_url = Column(String(500), nullable=True)
    followers = Column(Integer, nullable=False, default=0)

    country = relationship("Country", back_populates="cities")
    products = relationship("Product", back_populates="city")

    __table_args__ = (
        UniqueConstraint("name", "country_id", name="uq_city_name_country"),
    )

    def __repr__(self):
        return f"<City {self.name}>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    external_id = Column(String(200), nullable=False)
    source = Column(String(50), nullable=False)
    advertiser_id = Column(String(150), nullable=True)

    name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=False)
    affiliate_url = Column(String, nullable=False)

    product_image_url = Column(String(800), nullable=True)
    product_image_alt = Column(String(255), nullable=True)

    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=True)

    category = Column(String(80), nullable=True)
    style = Column(String(120), nullable=True)
    vibe = Column(String(120), nullable=True)

    is_best_seller = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    brand = relationship("Brand", back_populates="products")
    city = relationship("City", back_populates="products")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_product_external_source"),
    )

    def __repr__(self):
        return f"<Product {self.name} ({self.source})>"

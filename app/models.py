from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Numeric, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    # Using Google's `sub` as the stable user id for now (MVP friendly).
    # If you later want an internal UUID, add a separate column and migrate.
    id = Column(String(64), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    avatar = Column(String(500), nullable=True)

    # One-time welcome/about screen gate
    welcome_seen = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User {self.email}>"


class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(2), nullable=False, unique=True)  # e.g. "BR", "FR"
    name = Column(String(100), nullable=False, unique=True)

    brands = relationship("Brand", back_populates="country")

    def __repr__(self):
        return f"<Country {self.code}>"


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=False)

    # Optional: used by UI for handoff/logo display.
    # You can store a fully qualified URL (https://...) or a frontend-relative path (e.g. "/logos/macy.png").
    logo_url = Column(String(500), nullable=True)

    country = relationship("Country", back_populates="brands")

    __table_args__ = (
        UniqueConstraint("name", "country_id", name="uq_brand_name_country"),
    )

    def __repr__(self):
        return f"<Brand {self.name}>"
    



class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    # Affiliate / external identity
    external_id = Column(String(200), nullable=False)
    source = Column(String(50), nullable=False)  # e.g. "rakuten", "awin"

    # Merchant/advertiser id (useful for deterministic ordering + UI analytics)
    advertiser_id = Column(String(150), nullable=True)

    # Core info
    name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=False)

    affiliate_url = Column(String, nullable=False)

    # Optional: product image fields (used by UI's productImage)
    product_image_url = Column(String(800), nullable=True)
    product_image_alt = Column(String(255), nullable=True)

    # Relationships
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    brand = relationship("Brand", backref="products")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_product_external_source"),
    )

    def __repr__(self):
        return f"<Product {self.name} ({self.source})>"

from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Numeric, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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
    normalized_row_id = Column(
        Integer,
        ForeignKey("awin_product_normalized.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivation_reason = Column(Text, nullable=True)
    

class AwinProductFeedRaw(Base):
    __tablename__ = "awin_product_feed_raw"

    id = Column(Integer, primary_key=True, index=True)
    source_file = Column(String(255), nullable=False)

    advertiser_id = Column(String(50), nullable=True, index=True)
    advertiser_name = Column(String(255), nullable=True)
    external_product_id = Column(String(100), nullable=False)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    brand = Column(String(255), nullable=True)
    google_product_category = Column(String(500), nullable=True)
    product_type = Column(String(500), nullable=True)
    availability = Column(String(50), nullable=True, index=True)
    condition = Column(String(50), nullable=True)

    price_raw = Column(String(50), nullable=True)
    sale_price_raw = Column(String(50), nullable=True)

    link = Column(Text, nullable=True)
    aw_deep_link = Column(Text, nullable=True)
    image_link = Column(Text, nullable=True)
    additional_image_link = Column(Text, nullable=True)

    raw_payload = Column(Text, nullable=False)
    imported_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_file",
            "external_product_id",
            name="uq_awin_raw_source_file_external_product_id",
        ),
    )

    def __repr__(self):
        return f"<AwinProductFeedRaw {self.external_product_id} from {self.source_file}>"
    

class AwinProductNormalized(Base):
    __tablename__ = "awin_product_normalized"

    id = Column(Integer, primary_key=True, index=True)
    raw_id = Column(
        Integer,
        ForeignKey("awin_product_feed_raw.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    source = Column(String(50), nullable=False, default="awin")
    external_product_id = Column(String(100), nullable=False)
    advertiser_id = Column(String(50), nullable=True, index=True)
    advertiser_name = Column(String(255), nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    brand_name = Column(String(255), nullable=True)

    price_amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=True)

    affiliate_url = Column(Text, nullable=True)
    merchant_url = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)

    availability = Column(String(50), nullable=True, index=True)
    google_product_category = Column(String(500), nullable=True)
    product_type = Column(String(500), nullable=True)
    normalized_category = Column(String(80), nullable=True, index=True)

    is_usable = Column(Boolean, nullable=False, default=False, index=True)
    needs_review = Column(Boolean, nullable=False, default=True, index=True)

    review_status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    review_notes = Column(Text, nullable=True)

    promoted_at = Column(DateTime(timezone=True), nullable=True)
    promoted_product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )

    normalized_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "external_product_id",
            "source",
            name="uq_awin_normalized_external_source",
        ),
    )

    def __repr__(self):
        return f"<AwinProductNormalized {self.external_product_id} usable={self.is_usable}>"
    
class CatalogBrandControl(Base):
    __tablename__ = "catalog_brand_controls"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False, index=True)
    brand_key = Column(String(150), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    origin_country_code = Column(String(2), nullable=False)
    is_allowed = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "brand_key", name="uq_catalog_brand_controls_source_key"),
    )

    def __repr__(self):
        return f"<CatalogBrandControl {self.source}:{self.brand_key}>"

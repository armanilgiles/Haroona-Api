from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint,Numeric
from sqlalchemy.orm import relationship
from app.database import Base


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

    # Core info
    name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=False)

    affiliate_url = Column(String, nullable=False)

    # Relationships
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    brand = relationship("Brand", backref="products")

    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_product_external_source"),
    )

    def __repr__(self):
        return f"<Product {self.name} ({self.source})>"

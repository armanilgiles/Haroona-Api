from decimal import Decimal
from typing import List

from app.models import Brand, Product


def transform_rakuten_products(
    products: List[dict],
    brand_map: dict[str, Brand],
) -> List[Product]:
    transformed = []

    for p in products:
        brand = brand_map.get(p["brandName"])
        if not brand:
            continue  # unknown brand → skip or log

        product = Product(
            external_id=p["productId"],
            source="rakuten",
            advertiser_id=p.get("advertiserId"),
            name=p["productName"],
            price=Decimal(p["price"]),
            currency=p["currency"],
            affiliate_url=p["clickUrl"],
            # Some Rakuten feeds expose imageUrl/imageAlt (or similar). We store it if present.
            product_image_url=(p.get("productImageUrl") or p.get("imageUrl") or p.get("productImage")),
            product_image_alt=(p.get("productImageAlt") or p.get("imageAlt")),
            brand_id=brand.id,
        )

        transformed.append(product)

    return transformed


def normalize_rakuten(products: list[dict]) -> list[dict]:
    normalized = []

    for p in products:
        normalized.append({
            "external_id": f"rakuten-{p['productId']}",
            "name": p["productName"],
            "brand": p["brandName"],
            "price": float(p["price"]),
            "currency": p.get("currency", "USD"),
        })

    return normalized


from typing import List, Dict
from app.utils.normalize import normalize_brand
from app.data.brand_map import BRAND_MAP


from .errors import TransformError
from .logger import get_etl_logger

logger = get_etl_logger("etl.transform")

def transform_products(products: list[dict],source: str ) -> list[dict]:
    if not products:
        logger.warning("No products received for transformation")
        return []

    transformed = []

    for idx, product in enumerate(products):
        try:
            brand = product.get("brand")
            if not brand:
                raise TransformError("Missing brand")


            transformed.append({
                "external_id": product.get("productId"),
                "name": product.get("productName"),
                "brand": brand_name,
                "price": float(product.get("price", 0)),
                "currency": product.get("currency", "USD"),
                "source": "mock",
            })

        except Exception as e:
            logger.error(
                f"Transform failed at index={idx} product={product}",
                exc_info=True,
            )

    logger.info(f"Transformed {len(transformed)} products successfully")
    return transformed

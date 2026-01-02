from .logger import get_etl_logger

logger = get_etl_logger("etl.store")

# In-memory uniqueness store (temporary)
_seen_external_ids: set[str] = set()

def save_products(products: list[dict]) -> list[dict]:
    saved = []

    for product in products:
        external_id = product["external_id"]

        if external_id in _seen_external_ids:
            logger.info(f"Skipping duplicate product {external_id}")
            continue

        _seen_external_ids.add(external_id)
        saved.append(product)

    logger.info(f"Saved {len(saved)} new products")
    return saved

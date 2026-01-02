from .context import create_context
from .logger import get_etl_logger
from .rakuten_transform import normalize_rakuten
from .transform import transform_products
from .store import save_products
from .retry import retry
logger = get_etl_logger("etl.runner")



def run_rakuten_etl(raw_products: list[dict]) -> list[dict]:
    ctx = create_context(source="rakuten")

    logger.info(
        f"ETL started | run_id={ctx.run_id} | source={ctx.source}"
    )

    # 1️⃣ Normalize (source-specific)
    normalized = normalize_rakuten(raw_products)

    # 2️⃣ Canonical transform (no retries)
    transformed = transform_products(normalized, source="rakuten")

    # 3️⃣ Save with idempotency
    saved = save_products(transformed)

    logger.info(
        f"ETL completed | run_id={ctx.run_id} | saved={len(saved)}"
    )

    return saved



def run_etl(products: list[dict], source: str = "mock") -> list[dict]:
    ctx = create_context(source)

    logger.info(
        f"ETL started | run_id={ctx.run_id} | source={ctx.source}"
    )

    try:
        result = transform_products(products)

        logger.info(
            f"ETL completed | run_id={ctx.run_id} | records={len(result)}"
        )
        return result

    except Exception as e:
        logger.critical(
            f"ETL crashed | run_id={ctx.run_id}",
            exc_info=True,
        )
        raise


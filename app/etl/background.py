import asyncio
from .runner import run_rakuten_etl
from .logger import get_etl_logger

logger = get_etl_logger("etl.background")

async def run_rakuten_etl_background(raw_products: list[dict]) -> None:
    logger.info("Background ETL task scheduled")

    # Yield control back to event loop
    await asyncio.sleep(0)

    try:
        run_rakuten_etl(raw_products)
        logger.info("Background ETL task completed")
    except Exception:
        logger.exception("Background ETL task failed")

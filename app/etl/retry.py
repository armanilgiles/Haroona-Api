import time
from .errors import ExternalAPIError
from .logger import get_etl_logger

logger = get_etl_logger("etl.retry")

def retry(fn, retries: int = 3, delay: float = 0.5):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except ExternalAPIError as e:
            logger.warning(
                f"Retryable error (attempt {attempt}/{retries}): {e}"
            )

            if attempt == retries:
                logger.error("Max retries reached")
                raise

            time.sleep(delay)

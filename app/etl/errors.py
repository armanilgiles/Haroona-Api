class ETLError(Exception):
    """Base ETL exception"""

class TransformError(ETLError):
    """Bad data — do NOT retry"""

class ExternalAPIError(ETLError):
    """Temporary external failure — SAFE to retry"""

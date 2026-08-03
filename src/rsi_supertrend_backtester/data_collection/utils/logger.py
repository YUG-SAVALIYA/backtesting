"""
Structured logging setup for the backend application.
"""
import logging
import sys
from rsi_supertrend_backtester.data_collection.config import settings


def setup_logging() -> None:
    """Configure application-wide logging."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    # Clear any existing handlers to avoid duplicates on reload
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress verbose third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

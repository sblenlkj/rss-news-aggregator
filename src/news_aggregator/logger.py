"""Compact stdlib logging boundary for the local RSS application."""

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_NAMESPACE = "news_aggregator"


def setup_logger(level: str = "INFO") -> None:
    """Configure only our namespace, leaving Uvicorn and pytest handlers intact."""
    app_logger = logging.getLogger(_NAMESPACE)
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid NEWS_LOG_LEVEL: {level}")
    app_logger.setLevel(numeric_level)
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        app_logger.addHandler(handler)
    app_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

"""Periodic RSS polling task (to be started from FastAPI lifespan later)."""

import asyncio

from news_aggregator.logger import get_logger

from .service import NewsAggregatorService

logger = get_logger(__name__)


async def poll_forever(
    service: NewsAggregatorService,
    stop: asyncio.Event,
    interval_seconds: float = 60.0,
    *,
    start_immediately: bool = True,
) -> None:
    """Refresh immediately, then periodically, until shutdown is requested."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    logger.info("RSS poller running interval=%ss", interval_seconds)
    if not start_immediately:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            return
        except TimeoutError:
            pass
    while not stop.is_set():
        logger.info("RSS poll cycle started")
        try:
            results = await service.refresh_all()
            logger.info("RSS poll cycle finished successful=%d", len(results))
        except Exception:
            logger.exception("Uncaught error during RSS poll")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue

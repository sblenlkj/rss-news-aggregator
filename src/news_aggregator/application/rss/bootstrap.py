"""Idempotent startup RSS bootstrap for the local classroom demo.

The predefined list is intentionally explicit, not a general seeding framework.
New sources are registered once, without downloading news at startup.
"""

from collections.abc import Sequence

from news_aggregator.application.ports.storage import NewsStorage
from news_aggregator.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RSS_URLS: tuple[str, ...] = (
    "https://ria.ru/export/rss2/index.xml",
    "https://habr.com/ru/rss/articles/",
    "https://www.kommersant.ru/rss/science.xml",
    "https://www.mk.ru/rss/science/index.xml",
)


async def bootstrap_sources(
    storage: NewsStorage,
    *,
    test_feed_url: str,
    urls: Sequence[str] = DEFAULT_RSS_URLS,
) -> None:
    """Ensure demo sources exist without network access at startup.

    Existing sources keep identity and subscriptions. Disabled sources are not
    reactivated. Fetching articles is handled by manual refresh or polling.
    """
    desired = (*urls, test_feed_url)
    existing = {source.feed_url: source for source in await storage.list_sources()}
    added = 0

    for url in dict.fromkeys(desired):
        if url in existing:
            logger.info("Startup RSS already registered source=%s", existing[url].id)
            continue
        try:
            # Register metadata only; refresh is explicitly triggered later.
            source = await storage.add_source(url)
        except ValueError:
            # Another registration may have won the race; do not overwrite it.
            logger.warning("Startup RSS registration skipped URL=%s", url)
            continue
        existing[url] = source
        added += 1
        logger.info("Startup RSS registered source=%s", source.id)
    logger.info("Startup RSS bootstrap complete added=%d configured=%d", added, len(desired))

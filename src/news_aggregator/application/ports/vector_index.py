"""Cross-feature interface for indexing newly ingested news articles."""

from typing import Protocol

from news_aggregator.application.rss.models import Article


class VectorIndex(Protocol):
    async def upsert_articles(self, articles: list[Article]) -> None: ...


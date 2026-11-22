"""Small orchestration layer for registration and refreshing RSS feeds."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import httpx

from news_aggregator.logger import get_logger

from ..ports.storage import NewsStorage
from ..ports.vector_index import VectorIndex
from .models import NewsSource
from .ports import FeedReader

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    source_id: UUID
    fetched: int
    upserted: int


@dataclass(frozen=True, slots=True)
class RefreshFailure:
    source_id: UUID
    error: str


@dataclass(frozen=True, slots=True)
class RefreshReport:
    successful: tuple[RefreshResult, ...]
    failed: tuple[RefreshFailure, ...]


class NewsAggregatorService:
    def __init__(
        self,
        reader: FeedReader,
        storage: NewsStorage,
        vector_index: VectorIndex | None = None,
    ) -> None:
        self._reader = reader
        self._storage = storage
        self._vector_index = vector_index
        self._source_locks: dict[UUID, asyncio.Lock] = {}
        self._refresh_concurrency = 3

    async def register_source(self, url: str) -> NewsSource:
        """Persist source, then attempt ingestion immediately.

        A failed first refresh leaves the source registered for later retry.
        """
        source = await self._storage.add_source(url)
        logger.info("RSS source registered id=%s", source.id)
        try:
            await self.refresh_source(source.id)
        except Exception:
            logger.warning("Initial refresh failed for RSS source %s", source.id)
        return await self._storage.get_source(source.id)

    async def refresh_source(self, source_id: UUID) -> RefreshResult:
        # Different feeds may refresh concurrently; the same feed is serialized.
        lock = self._source_locks.setdefault(source_id, asyncio.Lock())
        async with lock:
            return await self._refresh_source_locked(source_id)

    async def _refresh_source_locked(self, source_id: UUID) -> RefreshResult:
        source = await self._storage.get_source(source_id)
        if not source.is_active:
            raise ValueError(f"Source {source_id} is inactive")
        logger.info("RSS refresh started source=%s", source.id)
        try:
            feed = await self._reader.fetch(source.feed_url)
            changed = await self._storage.save_articles(source_id, feed.articles)
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            logger.warning("RSS refresh failed source=%s error=%s", source_id, reason)
            await self._storage.record_refresh(source_id, error=reason)
            raise

        await self._storage.record_refresh(source_id)
        if changed and self._vector_index is not None:
            try:
                await self._vector_index.upsert_articles(changed)
            except Exception:
                # RSS is already persisted in SQLite. Keep ingestion successful:
                # failed vector indexing can be retried explicitly via backfill.
                logger.exception(
                    "Vector indexing failed source=%s changed=%d; "
                    "RSS articles remain in SQLite", source_id, len(changed),
                )
        logger.info("RSS refresh finished source=%s fetched=%d upserted=%d", source_id, len(feed.articles), len(changed))
        return RefreshResult(
            source_id=source_id,
            fetched=len(feed.articles),
            upserted=len(changed),
        )

    async def refresh_all_report(self) -> RefreshReport:
        """Refresh active sources independently and retain failure details."""
        successful: list[RefreshResult] = []
        failed: list[RefreshFailure] = []
        sources = await self._storage.list_sources()
        logger.info(
            "RSS refresh all started active_sources=%d",
            sum(source.is_active for source in sources),
        )
        semaphore = asyncio.Semaphore(self._refresh_concurrency)

        async def refresh_one(source: NewsSource) -> RefreshResult | RefreshFailure:
            async with semaphore:
                try:
                    return await self.refresh_source(source.id)
                except Exception as exc:
                    reason = str(exc).strip() or type(exc).__name__
                    if not isinstance(exc, httpx.HTTPError):
                        logger.exception(
                            "Unexpected RSS refresh failure source=%s", source.id
                        )
                    return RefreshFailure(source_id=source.id, error=reason)

        active_sources = [source for source in sources if source.is_active]
        # gather preserves source ordering and waits for every feed independently.
        outcomes = await asyncio.gather(
            *(refresh_one(source) for source in active_sources)
        )
        for outcome in outcomes:
            if isinstance(outcome, RefreshFailure):
                failed.append(outcome)
            else:
                successful.append(outcome)
        logger.info(
            "RSS refresh all finished successful=%d failed=%d",
            len(successful), len(failed),
        )
        return RefreshReport(tuple(successful), tuple(failed))

    async def refresh_all(self) -> list[RefreshResult]:
        """Compatibility for the background poller: successful refreshes only."""
        report = await self.refresh_all_report()
        return list(report.successful)


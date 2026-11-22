import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from news_aggregator.application.rss.models import (
    Article,
    NewsSource,
    ParsedArticle,
    ParsedFeed,
)
from news_aggregator.application.rss.service import NewsAggregatorService


def test_refresh_source_indexes_only_changed_articles():
    source_id = uuid4()
    source = NewsSource(id=source_id, feed_url="https://example.org/rss", title="Demo")
    parsed = ParsedArticle(title="Hello", summary="NLP news")

    class Reader:
        async def fetch(self, url):
            assert url == source.feed_url
            return ParsedFeed(title="Demo", feed_url=url, articles=(parsed,))

    class Storage:
        async def record_refresh(self, source_id_arg, *, error=None):
            assert source_id_arg == source_id
            assert error is None

        async def get_source(self, source_id_arg):
            assert source_id_arg == source_id
            return source

        async def save_articles(self, source_id_arg, articles):
            assert source_id_arg == source_id
            assert articles == (parsed,)
            return [Article(
                title=parsed.title,
                summary=parsed.summary,
                id=uuid4(),
                source_id=source_id,
                fetched_at=datetime.now(UTC),
            )]

    class Vector:
        def __init__(self):
            self.indexed = []

        async def upsert_articles(self, articles):
            self.indexed.extend(articles)

    index = Vector()
    result = asyncio.run(
        NewsAggregatorService(Reader(), Storage(), index).refresh_source(source_id)
    )
    assert result.fetched == 1
    assert result.upserted == 1
    assert len(index.indexed) == 1



def test_refresh_all_runs_different_sources_concurrently():
    """Two feeds start fetching before either is released."""
    first, second = uuid4(), uuid4()
    sources = [
        NewsSource(id=first, feed_url="https://example.org/a", title="A"),
        NewsSource(id=second, feed_url="https://example.org/b", title="B"),
    ]

    class Reader:
        def __init__(self):
            self.started = set()
            self.both_started = asyncio.Event()

        async def fetch(self, url):
            self.started.add(url)
            if len(self.started) == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), timeout=1)
            return ParsedFeed(title=url, feed_url=url, articles=())

    class Storage:
        async def list_sources(self):
            return sources

        async def get_source(self, source_id):
            return next(src for src in sources if src.id == source_id)

        async def save_articles(self, source_id, articles):
            return []

        async def record_refresh(self, source_id, *, error=None):
            assert error is None

    async def scenario():
        reader = Reader()
        result = await NewsAggregatorService(reader, Storage()).refresh_all_report()
        assert len(result.successful) == 2
        assert result.failed == ()
        assert len(reader.started) == 2

    asyncio.run(scenario())


def test_refresh_source_serializes_same_source():
    source_id = uuid4()
    source = NewsSource(id=source_id, feed_url="https://example.org/rss", title="Demo")

    class Reader:
        def __init__(self):
            self.active = 0
            self.maximum_active = 0

        async def fetch(self, url):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return ParsedFeed(title="Demo", feed_url=url, articles=())

    class Storage:
        async def get_source(self, source_id):
            return source

        async def save_articles(self, source_id, articles):
            return []

        async def record_refresh(self, source_id, *, error=None):
            pass

    async def scenario():
        reader = Reader()
        service = NewsAggregatorService(reader, Storage())
        await asyncio.gather(
            service.refresh_source(source_id), service.refresh_source(source_id)
        )
        assert reader.maximum_active == 1

    asyncio.run(scenario())

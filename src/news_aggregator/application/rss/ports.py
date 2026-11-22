"""RSS-only boundaries: fetching external feeds and publishing the test feed."""

from typing import Protocol

from news_aggregator.application.rss.models import ParsedFeed, TestFeedEntry


class FeedReader(Protocol):
    async def fetch(self, url: str) -> ParsedFeed: ...


class TestFeedPublisher(Protocol):
    __test__ = False  # Not a pytest test class.

    def publish(
        self, title: str, summary: str, tags: tuple[str, ...] = (),
        content: str | None = None,
    ) -> TestFeedEntry: ...

    def render_xml(self, base_url: str) -> bytes: ...


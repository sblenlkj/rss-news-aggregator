"""RSS feed values and persisted news entities."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ParsedArticle:
    """A normalized RSS/Atom entry before persistence (value object)."""

    title: str
    url: str | None = None
    external_id: str | None = None
    summary: str | None = None
    content: str | None = None
    tags: tuple[str, ...] = ()
    published_at: datetime | None = None

    @property
    def search_text(self) -> str:
        return "\n".join(
            part for part in (self.title, self.summary, self.content, " ".join(self.tags))
            if part
        )


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    """A parsed feed with normalized entries (value object)."""

    title: str
    feed_url: str
    articles: tuple[ParsedArticle, ...] = ()
    description: str | None = None
    site_url: str | None = None


@dataclass(frozen=True, slots=True)
class NewsSource:
    """Saved source and the status of its latest poll."""

    id: UUID
    feed_url: str
    title: str
    is_active: bool = True
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Article(ParsedArticle):
    """Saved article with identity, source and ingestion timestamp."""

    id: UUID
    source_id: UUID
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class TestFeedEntry:
    """Entry posted to our own RSS feed before normal ingestion."""

    __test__ = False  # Avoid collection as a pytest test class.

    id: UUID
    title: str
    summary: str
    published_at: datetime
    tags: tuple[str, ...] = ()
    content: str | None = None

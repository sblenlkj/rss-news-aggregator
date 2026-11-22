"""Persistence contracts shared by RSS ingestion, search and user configuration."""

from typing import Protocol
from uuid import UUID

from news_aggregator.application.models.user import User, UserConfig
from news_aggregator.application.rss.models import Article, NewsSource, ParsedArticle


class NewsStorage(Protocol):
    async def list_sources(self) -> list[NewsSource]: ...

    async def add_source(self, url: str, title: str | None = None) -> NewsSource: ...

    async def get_source(self, source_id: UUID) -> NewsSource: ...

    async def disable_source(self, source_id: UUID) -> None: ...

    async def record_refresh(
        self, source_id: UUID, *, error: str | None = None
    ) -> None: ...

    async def list_articles(
        self, source_ids: set[UUID] | None = None
    ) -> list[Article]: ...

    async def save_articles(
        self, source_id: UUID, articles: tuple[ParsedArticle, ...]
    ) -> list[Article]:
        """Upsert/deduplicate, returning articles that require reindexing."""
        ...


class UserStorage(Protocol):
    async def list_users(self) -> list[User]: ...

    async def add_user(self, name: str) -> User: ...

    async def get_user(self, user_id: UUID) -> User: ...

    async def get_user_config(self, user_id: UUID) -> UserConfig: ...

    async def save_user_config(
        self, user_id: UUID, config: UserConfig
    ) -> UserConfig: ...


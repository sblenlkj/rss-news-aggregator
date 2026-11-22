"""Async SQLAlchemy repository implementing application storage contracts."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from news_aggregator.application.models.user import User, UserConfig
from news_aggregator.application.rss.models import Article, NewsSource, ParsedArticle
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter
from news_aggregator.logger import get_logger

from .models import ArticleRow, FilterRow, SourceRow, UserRow, UserSourceRow

logger = get_logger(__name__)


def _utc(value: datetime | None) -> datetime | None:
    # SQLite stores timezone-naive datetimes even when DateTime(timezone=True).
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _identity(article: ParsedArticle) -> str:
    if article.external_id and article.external_id.strip():
        return "guid:" + article.external_id.strip()
    if article.url and article.url.strip():
        return "url:" + article.url.strip()
    return "text:" + hashlib.sha256(article.search_text.encode("utf-8")).hexdigest()


def _source(row: SourceRow) -> NewsSource:
    return NewsSource(
        id=UUID(row.id),
        feed_url=row.feed_url,
        title=row.title,
        is_active=row.is_active,
        last_checked_at=_utc(row.last_checked_at),
        last_success_at=_utc(row.last_success_at),
        last_error=row.last_error,
    )


def _article(row: ArticleRow) -> Article:
    return Article(
        id=UUID(row.id), source_id=UUID(row.source_id),
        title=row.title, url=row.url, external_id=row.external_id,
        summary=row.summary, content=row.content, tags=tuple(row.tags),
        published_at=_utc(row.published_at), fetched_at=_utc(row.fetched_at),
    )


def _user(row: UserRow) -> User:
    return User(id=UUID(row.id), name=row.name, created_at=_utc(row.created_at))


class SqliteRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sessions = session_factory

    async def list_sources(self) -> list[NewsSource]:
        async with self._sessions() as db:
            result = await db.scalars(select(SourceRow).order_by(SourceRow.title))
            return [_source(s) for s in result]

    async def get_source(self, source_id: UUID) -> NewsSource:
        async with self._sessions() as db:
            row = await db.get(SourceRow, str(source_id))
            if row is None:
                raise KeyError(f"Unknown RSS source: {source_id}")
            return _source(row)

    async def add_source(self, url: str, title: str | None = None) -> NewsSource:
        url = url.strip()
        if not url:
            raise ValueError("RSS URL must not be empty")
        async with self._sessions.begin() as db:
            existing = await db.scalar(select(SourceRow).where(SourceRow.feed_url == url))
            if existing is not None:
                raise ValueError("RSS feed already registered")
            row = SourceRow(feed_url=url, title=title or url)
            db.add(row)
            await db.flush()
            logger.info("SQLite source created id=%s", row.id)
            return _source(row)

    async def record_refresh(self, source_id: UUID, *, error: str | None = None) -> None:
        async with self._sessions.begin() as db:
            row = await db.get(SourceRow, str(source_id))
            if row is None:
                raise KeyError(f"Unknown RSS source: {source_id}")
            now = datetime.now(UTC)
            row.last_checked_at = now
            row.last_error = error
            if error is None:
                row.last_success_at = now

    async def save_articles(
        self, source_id: UUID, articles: tuple[ParsedArticle, ...]
    ) -> list[Article]:
        changed: list[Article] = []
        async with self._sessions.begin() as db:
            if await db.get(SourceRow, str(source_id)) is None:
                raise KeyError(f"Unknown RSS source: {source_id}")
            for entry in articles:
                identity = _identity(entry)
                row = await db.scalar(
                    select(ArticleRow).where(
                        ArticleRow.source_id == str(source_id),
                        ArticleRow.identity == identity,
                    )
                )
                if row is not None and (
                    row.title == entry.title
                    and row.summary == entry.summary
                    and row.content == entry.content
                    and tuple(row.tags) == entry.tags
                ):
                    continue
                if row is None:
                    row = ArticleRow(source_id=str(source_id), identity=identity)
                    db.add(row)
                row.title = entry.title
                row.url = entry.url
                row.external_id = entry.external_id
                row.summary = entry.summary
                row.content = entry.content
                row.tags = list(entry.tags)
                row.published_at = entry.published_at
                row.fetched_at = datetime.now(UTC)
                await db.flush()
                changed.append(_article(row))
        logger.info("SQLite articles upsert source=%s received=%d changed=%d", source_id, len(articles), len(changed))
        return changed

    async def disable_source(self, source_id: UUID) -> None:
        async with self._sessions.begin() as db:
            row = await db.get(SourceRow, str(source_id))
            if row is None:
                raise KeyError(f"Unknown RSS source: {source_id}")
            row.is_active = False
            logger.info("SQLite source disabled id=%s", source_id)

    async def list_articles(self, source_ids: set[UUID] | None = None) -> list[Article]:
        if source_ids == set():
            return []
        async with self._sessions() as db:
            stmt = select(ArticleRow)
            if source_ids is not None:
                stmt = stmt.where(ArticleRow.source_id.in_([str(x) for x in source_ids]))
            rows = (await db.scalars(stmt)).all()
            articles = [_article(row) for row in rows]
            return sorted(
                articles, key=lambda a: a.published_at or a.fetched_at, reverse=True
            )

    async def list_users(self) -> list[User]:
        async with self._sessions() as db:
            return [_user(row) for row in (await db.scalars(select(UserRow))).all()]

    async def add_user(self, name: str) -> User:
        if not name.strip():
            raise ValueError("User name must not be empty")
        async with self._sessions.begin() as db:
            row = UserRow(name=name.strip())
            db.add(row)
            await db.flush()
            logger.info("SQLite user created id=%s", row.id)
            return _user(row)

    async def get_user(self, user_id: UUID) -> User:
        async with self._sessions() as db:
            row = await db.get(UserRow, str(user_id))
            if row is None:
                raise KeyError(f"Unknown user: {user_id}")
            return _user(row)

    async def get_user_config(self, user_id: UUID) -> UserConfig:
        async with self._sessions() as db:
            user = await db.get(UserRow, str(user_id))
            if user is None:
                raise KeyError(f"Unknown user: {user_id}")
            sources = (await db.scalars(select(UserSourceRow).where(
                UserSourceRow.user_id == str(user_id)
            ))).all()
            filters = (await db.scalars(select(FilterRow).where(
                FilterRow.user_id == str(user_id)
            ))).all()
            return UserConfig(
                source_ids=tuple(UUID(row.source_id) for row in sources),
                add_synonyms=user.add_synonyms,
                filters=tuple(
                    KeywordFilter(id=UUID(row.id), value=row.value, enabled=row.enabled)
                    if row.type == "keyword"
                    else SemanticFilter(
                        id=UUID(row.id), value=row.value, enabled=row.enabled,
                        threshold=row.threshold
                    )
                    for row in filters
                ),
            )

    async def save_user_config(self, user_id: UUID, config: UserConfig) -> UserConfig:
        if len(set(config.source_ids)) != len(config.source_ids):
            raise ValueError("Duplicate source in configuration")
        if len({f.id for f in config.filters}) != len(config.filters):
            raise ValueError("Duplicate filter id")
        async with self._sessions.begin() as db:
            user = await db.get(UserRow, str(user_id))
            if user is None:
                raise KeyError(f"Unknown user: {user_id}")
            source_ids = {row for row in (await db.scalars(select(SourceRow.id).where(
                SourceRow.id.in_([str(x) for x in config.source_ids])
            ))).all()}
            if source_ids != {str(x) for x in config.source_ids}:
                raise ValueError("Unknown RSS source in user configuration")
            await db.execute(delete(UserSourceRow).where(UserSourceRow.user_id == str(user_id)))
            await db.execute(delete(FilterRow).where(FilterRow.user_id == str(user_id)))
            db.add_all(
                UserSourceRow(user_id=str(user_id), source_id=str(source_id))
                for source_id in config.source_ids
            )
            for item in config.filters:
                db.add(FilterRow(
                    id=str(item.id), user_id=str(user_id), type=item.type,
                    value=item.value, enabled=item.enabled,
                    threshold=item.threshold if isinstance(item, SemanticFilter) else None,
                ))
            user.add_synonyms = config.add_synonyms
            user.config_version += 1
            logger.info("SQLite user config saved user=%s sources=%d filters=%d", user_id, len(config.source_ids), len(config.filters))
        return config

"""JSON-file storage for small, single-process RSS aggregator demos.

Writes are atomic per JSON file. A single asyncio lock guards modifications
within one Python process. Do not run multiple independent writers/workers.
"""

import asyncio
import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from news_aggregator.application.rss.models import Article, NewsSource, ParsedArticle


def _now() -> datetime:
    return datetime.now(UTC)


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _identity(article: ParsedArticle) -> str:
    """Stable within one source: GUID, then link, then normalized text hash."""
    if article.external_id:
        return "guid:" + article.external_id.strip()
    if article.url:
        return "url:" + article.url.strip()
    digest = hashlib.sha256(article.search_text.encode("utf-8")).hexdigest()
    return "text:" + digest


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            name = tmp.name
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def _load_json(path: Path, default: list) -> list:
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(f"Expected JSON array in {path}")
    return data


def _source_to_json(src: NewsSource) -> dict:
    return {
        "id": str(src.id),
        "feed_url": src.feed_url,
        "title": src.title,
        "is_active": src.is_active,
        "last_checked_at": (
            src.last_checked_at.isoformat() if src.last_checked_at else None
        ),
        "last_success_at": (
            src.last_success_at.isoformat() if src.last_success_at else None
        ),
        "last_error": src.last_error,
    }


def _source_from_json(raw: dict) -> NewsSource:
    return NewsSource(
        id=UUID(raw["id"]),
        feed_url=raw["feed_url"],
        title=raw["title"],
        is_active=raw.get("is_active", True),
        last_checked_at=_datetime(raw.get("last_checked_at")),
        last_success_at=_datetime(raw.get("last_success_at")),
        last_error=raw.get("last_error"),
    )


def _article_to_json(article: Article) -> dict:
    return {
        **asdict(article),
        "id": str(article.id),
        "source_id": str(article.source_id),
        "published_at": (
            article.published_at.isoformat() if article.published_at else None
        ),
        "fetched_at": article.fetched_at.isoformat(),
        "tags": list(article.tags),
        "identity": _identity(article),
    }


def _article_from_json(raw: dict) -> Article:
    return Article(
        id=UUID(raw["id"]),
        source_id=UUID(raw["source_id"]),
        title=raw["title"],
        url=raw.get("url"),
        external_id=raw.get("external_id"),
        summary=raw.get("summary"),
        tags=tuple(raw.get("tags", ())),
        published_at=_datetime(raw.get("published_at")),
        fetched_at=datetime.fromisoformat(raw["fetched_at"]),
    )


class JsonNewsStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._sources_file = self.data_dir / "sources.json"
        self._articles_file = self.data_dir / "articles.json"
        self._lock = asyncio.Lock()

    async def list_sources(self) -> list[NewsSource]:
        async with self._lock:
            return [
                _source_from_json(item)
                for item in _load_json(self._sources_file, [])
            ]

    async def add_source(
        self, url: str, title: str | None = None
    ) -> NewsSource:
        url = url.strip()
        if not url:
            raise ValueError("RSS URL must not be empty")
        async with self._lock:
            sources = [
                _source_from_json(item)
                for item in _load_json(self._sources_file, [])
            ]
            if any(s.feed_url == url for s in sources):
                raise ValueError("RSS feed already registered")
            source = NewsSource(
                id=uuid4(), feed_url=url, title=title or url
            )
            _atomic_json(
                self._sources_file,
                [_source_to_json(s) for s in (*sources, source)],
            )
            return source

    async def get_source(self, source_id: UUID) -> NewsSource:
        sources = await self.list_sources()
        for source in sources:
            if source.id == source_id:
                return source
        raise KeyError(f"Unknown RSS source: {source_id}")

    async def record_refresh(
        self, source_id: UUID, *, error: str | None = None
    ) -> None:
        async with self._lock:
            sources = [
                _source_from_json(item)
                for item in _load_json(self._sources_file, [])
            ]
            now = _now()
            found = False
            updated = []
            for source in sources:
                if source.id == source_id:
                    found = True
                    source = replace(
                        source,
                        last_checked_at=now,
                        last_success_at=now if error is None else source.last_success_at,
                        last_error=error,
                    )
                updated.append(source)
            if not found:
                raise KeyError(f"Unknown RSS source: {source_id}")
            _atomic_json(self._sources_file, [_source_to_json(s) for s in updated])

    async def save_articles(
        self, source_id: UUID, articles: tuple[ParsedArticle, ...]
    ) -> list[Article]:
        async with self._lock:
            raw = _load_json(self._articles_file, [])
            existing = {
                (a["source_id"], a.get("identity") or _identity(
                    _article_from_json(a)
                )): a
                for a in raw
            }
            changed: list[Article] = []
            now = _now()
            for parsed in articles:
                key = (str(source_id), _identity(parsed))
                previous = existing.get(key)
                if previous is not None:
                    # Identical news in repeated polls is not reindexed.
                    if (
                        previous["title"] == parsed.title
                        and previous.get("summary") == parsed.summary
                        and tuple(previous.get("tags", [])) == parsed.tags
                    ):
                        continue
                    identity = UUID(previous["id"])
                else:
                    identity = uuid4()
                item = Article(
                    id=identity,
                    source_id=source_id,
                    title=parsed.title,
                    url=parsed.url,
                    external_id=parsed.external_id,
                    summary=parsed.summary,
                    tags=parsed.tags,
                    published_at=parsed.published_at,
                    fetched_at=now,
                )
                existing[key] = _article_to_json(item)
                changed.append(item)
            if changed:
                _atomic_json(self._articles_file, list(existing.values()))
            return changed

    async def list_articles(
        self, source_ids: set[UUID] | None = None
    ) -> list[Article]:
        async with self._lock:
            articles = [
                _article_from_json(item)
                for item in _load_json(self._articles_file, [])
            ]
        if source_ids is not None:
            articles = [a for a in articles if a.source_id in source_ids]
        return sorted(
            articles, key=lambda a: a.published_at or a.fetched_at,
            reverse=True,
        )

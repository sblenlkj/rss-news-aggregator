"""RSS/Atom ingestion via feedparser.

Network URL validation and SSRF protection must be added before exposing
arbitrary feed URLs to untrusted users. The synchronous parse_feed() function
can be tested without network access.
"""

import asyncio
from calendar import timegm
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import feedparser
import httpx

from news_aggregator.application.rss.models import ParsedArticle, ParsedFeed
from news_aggregator.logger import get_logger

logger = get_logger(__name__)
_MAX_FEED_BYTES = 2_000_000


def _safe_feed_url(url: str) -> str:
    """Include only the host and path, never credentials or query tokens."""
    parts = urlsplit(url)
    return f"{parts.hostname or '<unknown host>'}{parts.path}"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    result = " ".join(unescape("".join(parser.parts)).split())
    return result or None


def _published(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(timegm(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_feed(xml: bytes, feed_url: str) -> ParsedFeed:
    """Normalize RSS 2.0 or Atom into our internal models."""
    parsed = feedparser.parse(xml)
    if not parsed.version and not parsed.entries:
        raise ValueError("Response is not a recognizable RSS/Atom feed")

    articles: list[ParsedArticle] = []
    for entry in parsed.entries:
        title = _plain_text(entry.get("title"))
        summary = _plain_text(entry.get("summary"))
        # feedparser normalizes Atom <content> and RSS content:encoded here.
        # Some feeds provide several content variants; prefer the first
        # non-empty textual representation, without replacing the summary.
        content = next(
            (
                text for part in (entry.get("content") or [])
                if (text := _plain_text(part.get("value")))
            ),
            None,
        )
        if not any((title, summary, content)):
            continue
        # Keep malformed/atypical entries when there is still searchable text.
        title = title or "(без заголовка)"

        raw_tags = (tag.get("term", "") for tag in entry.get("tags", []))
        tags = tuple(dict.fromkeys(tag.strip() for tag in raw_tags if tag.strip()))

        articles.append(
            ParsedArticle(
                title=title,
                url=entry.get("link") or None,
                external_id=entry.get("id") or None,
                summary=summary,
                content=content,
                tags=tags,
                published_at=_published(
                    entry.get("published_parsed") or entry.get("updated_parsed")
                ),
            )
        )

    feed = parsed.feed
    logger.info("RSS parsed host_path=%s format=%s entries=%d articles=%d", _safe_feed_url(feed_url), parsed.version, len(parsed.entries), len(articles))
    return ParsedFeed(
        title=_plain_text(feed.get("title")) or feed_url,
        feed_url=feed_url,
        description=_plain_text(feed.get("subtitle")),
        site_url=feed.get("link") or None,
        articles=tuple(articles),
    )


class FeedparserReader:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, url: str) -> ParsedFeed:
        """Read RSS, retrying once for transient connection/read timeouts.

        Client-provided timeouts are respected; retries apply to both client
        ownership modes. Redirects and HTTP 4xx errors are not retried.
        """
        if self._client is not None:
            return await self._fetch_retry(self._client, url)
        timeout = httpx.Timeout(10.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            return await self._fetch_retry(client, url)

    async def _fetch_retry(self, client: httpx.AsyncClient, url: str) -> ParsedFeed:
        for attempt in (1, 2):
            try:
                return await self._fetch_with(client, url)
            except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                if attempt == 2:
                    raise
                logger.warning(
                    "RSS transient timeout host_path=%s attempt=%d/2 type=%s",
                    _safe_feed_url(url), attempt, type(exc).__name__,
                )
                await asyncio.sleep(0.5)
        raise AssertionError("Unreachable retry state")

    async def _fetch_with(self, client: httpx.AsyncClient, url: str) -> ParsedFeed:
        logger.info("RSS HTTP GET host_path=%s", _safe_feed_url(url))
        async with client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Feed redirects are not supported yet")
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > _MAX_FEED_BYTES:
                    raise ValueError("RSS feed exceeds configured size limit")
        logger.info("RSS HTTP received host_path=%s status=%d bytes=%d", _safe_feed_url(url), response.status_code, len(chunks))
        return parse_feed(bytes(chunks), url)

"""Network retry behavior: no live HTTP calls."""

import asyncio

import httpx
import pytest

from news_aggregator.adapters.rss import FeedparserReader

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<title>Testing</title><item><title>Works</title></item>
</channel></rss>"""


def test_rss_reader_retries_connect_timeout_once():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("")
        return httpx.Response(200, content=RSS)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            feed = await FeedparserReader(client).fetch("https://example.org/rss")
            assert len(feed.articles) == 1

    asyncio.run(scenario())
    assert attempts == 2


def test_rss_reader_gives_up_after_second_timeout():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(httpx.ConnectTimeout):
                await FeedparserReader(client).fetch("https://example.org/rss")

    asyncio.run(scenario())
    assert attempts == 2


def test_rss_reader_does_not_retry_http_403():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(403, text="Forbidden")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await FeedparserReader(client).fetch("https://example.org/rss")

    asyncio.run(scenario())
    assert attempts == 1

"""Startup feed bootstrap: idempotence, refresh and error isolation."""

from fastapi.testclient import TestClient

from news_aggregator.application.rss.bootstrap import DEFAULT_RSS_URLS
from news_aggregator.application.rss.models import ParsedArticle, ParsedFeed
from news_aggregator.main import create_app

GOOD = "https://example.org/good.xml"
BAD = "https://example.org/unavailable.xml"


class DemoReader:
    def __init__(self):
        self.calls = []

    async def fetch(self, url: str) -> ParsedFeed:
        self.calls.append(url)
        if url == BAD:
            raise RuntimeError("Upstream feed unavailable")
        return ParsedFeed(
            title="Good news",
            feed_url=url,
            articles=(
                ParsedArticle(
                    title="Искусственный интеллект",
                    external_id="first",
                ),
            ),
        )


def test_bootstrap_is_idempotent_and_refreshes_existing_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_NAVEC_PATH", "")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "")
    monkeypatch.setenv("NEWS_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    db = tmp_path / "news.db"
    publisher = tmp_path / "publisher.json"
    reader = DemoReader()

    def build():
        return create_app(
            db_path=db, publisher_path=publisher, reader=reader,
            enable_polling=False, enable_bootstrap=True,
            bootstrap_urls=(GOOD, BAD),
        )

    with TestClient(build()) as client:
        sources = client.get("/api/v1/sources").json()
        assert len(sources) == 3  # two predefined and local test RSS
        assert len({src["feed_url"] for src in sources}) == 3
        assert client.get("/api/v1/articles").json() == []
        assert reader.calls == []  # startup must never fetch RSS
        first_ids = {src["feed_url"]: src["id"] for src in sources}
        assert all(src["last_checked_at"] is None for src in sources)
        published = client.post("/api/v1/test-feed/articles", json={
            "title": "Локальный эксперимент", "summary": "Тестовый RSS",
        })
        assert published.status_code == 201

    # Reopening the same database must neither duplicate sources nor fetch.
    with TestClient(build()) as client:
        sources = client.get("/api/v1/sources").json()
        assert {src["feed_url"]: src["id"] for src in sources} == first_ids
        assert client.get("/api/v1/articles").json() == []
        assert reader.calls == []

        # Sync is explicit; one faulty feed must not block other feeds.
        refreshed = client.post("/api/v1/sources/refresh")
        assert refreshed.status_code == 200
        report = refreshed.json()
        assert len(report["successful"]) == 2  # good external + fake-read local
        assert len(report["failed"]) == 1
        assert report["failed"][0]["source_id"] == first_ids[BAD]
        assert "Upstream feed unavailable" in report["failed"][0]["error"]
        assert reader.calls.count(GOOD) == 1
        assert reader.calls.count(BAD) == 1
        assert len(client.get("/api/v1/articles").json()) == 2
        assert next(src for src in client.get("/api/v1/sources").json()
                    if src["feed_url"] == BAD)["last_error"]
        assert client.delete(f"/api/v1/sources/{first_ids[GOOD]}").status_code == 204

    with TestClient(build()) as client:
        assert reader.calls.count(GOOD) == 1
        assert reader.calls.count(BAD) == 1
        sources = client.get("/api/v1/sources").json()
        assert len(sources) == 3
        assert next(src for src in sources if src["feed_url"] == GOOD)["is_active"] is False


def test_default_rss_sources_are_the_verified_feeds():
    assert DEFAULT_RSS_URLS == (
        "https://ria.ru/export/rss2/index.xml",
        "https://habr.com/ru/rss/articles/",
        "https://www.kommersant.ru/rss/science.xml",
        "https://www.mk.ru/rss/science/index.xml",
    )

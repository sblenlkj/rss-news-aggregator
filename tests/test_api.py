"""Test real HTTP routes with SQLite, no external RSS HTTP requests."""

from fastapi.testclient import TestClient

from news_aggregator.adapters.rss import parse_feed
from news_aggregator.application.rss.models import ParsedArticle, ParsedFeed
from news_aggregator.main import create_app


class FakeFeedReader:
    def __init__(self):
        self.entries = (ParsedArticle(
            title="Artificial intelligence news",
            summary="Embedding models released",
            external_id="item-1",
            tags=("NLP",),
        ),)

    async def fetch(self, url: str) -> ParsedFeed:
        return ParsedFeed(
            title="Fake Feed", feed_url=url, articles=self.entries
        )


def test_http_users_sources_refresh_and_test_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "")
    monkeypatch.setenv("NEWS_NAVEC_PATH", "")  # no local weights in this test
    reader = FakeFeedReader()
    app = create_app(
        db_path=tmp_path / "news.db",
        publisher_path=tmp_path / "test-feed.json",
        reader=reader,
        enable_polling=False,
        enable_bootstrap=False,
    )
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "News Studio" in home.text
        assert client.get("/static/app.js").status_code == 200
        capabilities = client.get("/api/v1/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["keyword"] is True
        assert capabilities.json()["semantic_enabled"] is False
        assert capabilities.json()["synonyms_enabled"] is False

        first = client.post("/api/v1/users", json={"name": "Alice"})
        assert first.status_code == 201, first.text
        alice = first.json()
        assert len(client.get("/api/v1/users").json()) == 1

        source_resp = client.post("/api/v1/sources", json={
            "url": "https://example.org/rss"
        })
        assert source_resp.status_code == 201, source_resp.text
        source = source_resp.json()
        sid = source["id"]
        assert source["last_success_at"] is not None

        keyword_search = client.post("/api/v1/search", json={
            "source_ids": [sid],
            "filters": [{"type": "keyword", "value": "intelligence"}],
        })
        assert keyword_search.status_code == 200, keyword_search.text
        assert keyword_search.json()["total"] == 1
        assert keyword_search.json()["items"][0]["matches"][0]["engine"] == "bm25"

        semantic_search = client.post("/api/v1/search", json={
            "source_ids": [sid],
            "filters": [{"type": "semantic", "value": "AI"}],
            "mode": "semantic",
        })
        assert semantic_search.status_code == 501
        preview = client.post("/api/v1/search/expand", json={
            "source_ids": [sid], "keywords": ["intelligence"],
        })
        assert preview.status_code == 501

        invalid_weights = client.post("/api/v1/search", json={
            "source_ids": [sid],
            "filters": [{"type": "keyword", "value": "AI"}],
            "mode": "hybrid",
            "bm25_weight": 0.8, "semantic_weight": 0.6,
        })
        assert invalid_weights.status_code == 422

        articles = client.get("/api/v1/articles").json()
        assert len(articles) == 1
        assert articles[0]["title"] == "Artificial intelligence news"
        assert client.post(f"/api/v1/sources/{sid}/refresh").status_code == 200
        assert len(client.get("/api/v1/articles").json()) == 1

        config = {"source_ids": [sid], "add_synonyms": True, "filters": [
            {"type": "keyword", "value": "AI"},
            {"type": "semantic", "value": "NLP", "threshold": 0.6},
        ]}
        saved = client.put(
            f"/api/v1/users/{alice['id']}/config", json=config
        )
        assert saved.status_code == 200, saved.text
        assert len(saved.json()["filters"]) == 2
        assert saved.json()["add_synonyms"] is True
        assert client.get(
            f"/api/v1/users/{alice['id']}/config"
        ).json()["source_ids"] == [sid]

        bob = client.post("/api/v1/users", json={"name": "Bob"}).json()
        assert client.get(
            f"/api/v1/users/{bob['id']}/config"
        ).json() == {"source_ids": [], "filters": [], "add_synonyms": False}

        pub = client.post("/api/v1/test-feed/articles", json={
            "title": "Test story", "summary": "From internal feed", "tags": ["NLP"]
        })
        assert pub.status_code == 201, pub.text
        feed_response = client.get("/test-feed/rss.xml")
        assert feed_response.status_code == 200
        parsed = parse_feed(feed_response.content, "http://localhost/test-feed/rss.xml")
        assert parsed.articles[0].title == "Test story"
        assert len(client.get("/api/v1/articles").json()) == 1

        assert client.delete(f"/api/v1/sources/{sid}").status_code == 204
        assert client.get(f"/api/v1/sources/{sid}/status").json()["is_active"] is False
        assert client.post(f"/api/v1/sources/{sid}/refresh").status_code == 409


def test_api_validation_and_missing_records(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "")
    monkeypatch.setenv("NEWS_NAVEC_PATH", "")
    app = create_app(
        db_path=tmp_path / "news.db",
        publisher_path=tmp_path / "test-feed.json",
        reader=FakeFeedReader(),
        enable_polling=False,
        enable_bootstrap=False,
    )
    with TestClient(app) as client:
        assert client.post("/api/v1/users", json={"name": ""}).status_code == 422
        assert client.get("/api/v1/users/00000000-0000-0000-0000-000000000001").status_code == 404
        assert client.post("/api/v1/sources", json={"url": "not-url"}).status_code == 422



def test_refresh_timeout_has_nonempty_error_and_persists_status(tmp_path, monkeypatch):
    """Some httpx failures have an empty str(exc), e.g. ConnectTimeout."""
    import httpx

    class TimeoutFeedReader:
        async def fetch(self, url):
            raise httpx.ConnectTimeout("")

    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "")
    monkeypatch.setenv("NEWS_NAVEC_PATH", "")
    app = create_app(
        db_path=tmp_path / "news.db",
        publisher_path=tmp_path / "test-feed.json",
        reader=TimeoutFeedReader(),
        enable_polling=False,
        enable_bootstrap=False,
    )
    with TestClient(app) as client:
        source = client.post(
            "/api/v1/sources", json={"url": "https://example.org/feed.xml"}
        ).json()
        response = client.post(
            f"/api/v1/sources/{source['id']}/refresh"
        )
        assert response.status_code == 502
        assert "ConnectTimeout" in response.json()["detail"]
        status = client.get(
            f"/api/v1/sources/{source['id']}/status"
        ).json()
        assert status["last_error"] == "ConnectTimeout"


def test_semantic_backfill_disabled_without_index(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "")
    app = create_app(
        db_path=tmp_path / "news.db",
        publisher_path=tmp_path / "test-feed.json",
        enable_polling=False,
        enable_bootstrap=False,
    )
    with TestClient(app) as client:
        assert client.post("/api/v1/search/index").status_code == 501

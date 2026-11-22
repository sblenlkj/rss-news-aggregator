import asyncio
from datetime import UTC, datetime

from news_aggregator.adapters.json_storage import JsonNewsStorage
from news_aggregator.application.rss.models import ParsedArticle


def test_json_store_persists_sources_articles_and_refresh_state(tmp_path):
    async def scenario():
        store = JsonNewsStorage(tmp_path)
        src = await store.add_source("https://example.com/rss", "Example")
        assert src.title == "Example"
        entry = ParsedArticle(
            title="Model update",
            external_id="guid-1",
            summary="Short summary",
            tags=("NLP",),
            published_at=datetime(2026, 11, 16, tzinfo=UTC),
        )
        changed = await store.save_articles(src.id, (entry,))
        assert len(changed) == 1
        assert changed[0].search_text == "Model update\nShort summary\nNLP"

        # Polling the same feed again must not insert duplicates.
        assert await store.save_articles(src.id, (entry,)) == []
        await store.record_refresh(src.id)
        reloaded = JsonNewsStorage(tmp_path)
        assert (await reloaded.get_source(src.id)).last_success_at is not None
        articles = await reloaded.list_articles({src.id})
        assert len(articles) == 1
        assert articles[0].id == changed[0].id

        await reloaded.record_refresh(src.id, error="Temporary failure")
        failed = await JsonNewsStorage(tmp_path).get_source(src.id)
        assert failed.last_error == "Temporary failure"
        assert failed.last_success_at is not None
        assert await reloaded.list_articles(set()) == []

    asyncio.run(scenario())


def test_json_store_updates_same_guid_without_duplicate(tmp_path):
    async def scenario():
        store = JsonNewsStorage(tmp_path)
        source = await store.add_source("https://example.com/rss")
        first = ParsedArticle(title="AI", external_id="same")
        second = ParsedArticle(title="AI updated", external_id="same")
        before = (await store.save_articles(source.id, (first,)))[0]
        after = (await store.save_articles(source.id, (second,)))[0]
        assert after.id == before.id
        assert len(await store.list_articles()) == 1

    asyncio.run(scenario())


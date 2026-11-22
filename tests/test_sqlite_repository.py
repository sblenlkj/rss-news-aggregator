"""SQLite adapter integration tests: real temp database, no network."""

import asyncio
from uuid import UUID, uuid4

import pytest

from news_aggregator.adapters.outbound.persistence.database import (
    create_schema,
    sessions,
    sqlite_engine,
)
from news_aggregator.adapters.outbound.persistence.repository import SqliteRepository
from news_aggregator.application.models.user import UserConfig
from news_aggregator.application.rss.models import ParsedArticle
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter


def test_sqlite_sources_articles_users_and_config(tmp_path):
    async def scenario():
        engine = sqlite_engine(tmp_path / "news.db")
        try:
            await create_schema(engine)
            repo = SqliteRepository(sessions(engine))
            source = await repo.add_source("https://example.com/rss", "Example")
            article = ParsedArticle(
                title="New AI", summary="Semantic embeddings", content="Full text of the new model",
                external_id="item-1", tags=("NLP",)
            )
            one = await repo.save_articles(source.id, (article,))
            assert len(one) == 1
            assert one[0].content == "Full text of the new model"
            assert await repo.save_articles(source.id, (article,)) == []
            updated = await repo.save_articles(source.id, (
                ParsedArticle(
                    title="New AI updated", summary="Semantic embeddings", content="Full text of the new model",
                    external_id="item-1", tags=("NLP",)
                ),
            ))
            assert len(updated) == 1
            assert updated[0].id == one[0].id
            assert len(await repo.list_articles({source.id})) == 1
            assert await repo.list_articles(set()) == []

            await repo.record_refresh(source.id)
            assert (await repo.get_source(source.id)).last_success_at is not None
            await repo.record_refresh(source.id, error="network failure")
            assert (await repo.get_source(source.id)).last_error == "network failure"

            alice = await repo.add_user("Alice")
            bob = await repo.add_user("Bob")
            config = UserConfig(
                source_ids=(source.id,),
                add_synonyms=True,
                filters=(
                    KeywordFilter(id=uuid4(), value="AI"),
                    SemanticFilter(id=uuid4(), value="neural networks", threshold=0.6),
                ),
            )
            await repo.save_user_config(alice.id, config)
            assert await repo.get_user_config(alice.id) == config
            assert (await repo.get_user_config(alice.id)).add_synonyms is True
            assert (await repo.get_user_config(bob.id)) == UserConfig()

            # Full replace, including clearing old relations.
            await repo.save_user_config(alice.id, UserConfig())
            assert await repo.get_user_config(alice.id) == UserConfig()
            with pytest.raises(ValueError):
                await repo.save_user_config(
                    alice.id, UserConfig(source_ids=(uuid4(),))
                )
            assert await repo.get_user_config(bob.id) == UserConfig()
        finally:
            await engine.dispose()

        # Reopen same physical SQLite file: data must persist across restarts.
        reopened = sqlite_engine(tmp_path / "news.db")
        try:
            repo = SqliteRepository(sessions(reopened))
            assert len(await repo.list_sources()) == 1
            assert len(await repo.list_articles()) == 1
            assert (await repo.list_articles())[0].content == "Full text of the new model"
            assert len(await repo.list_users()) == 2
        finally:
            await reopened.dispose()

    asyncio.run(scenario())


def test_existing_sqlite_schema_gains_content_without_data_loss(tmp_path):
    """A preexisting articles table must be migrated, not reset."""
    from sqlalchemy import text

    async def scenario():
        engine = sqlite_engine(tmp_path / "existing.db")
        try:
            # Create the old articles table before initializing the current ORM.
            async with engine.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE articles (
                        id VARCHAR(36) PRIMARY KEY,
                        source_id VARCHAR(36) NOT NULL,
                        identity TEXT NOT NULL,
                        title TEXT NOT NULL,
                        url TEXT,
                        external_id TEXT,
                        summary TEXT,
                        tags JSON NOT NULL,
                        published_at DATETIME,
                        fetched_at DATETIME NOT NULL,
                        UNIQUE(source_id, identity)
                    )
                """))
                await conn.execute(text("""
                    INSERT INTO articles
                        (id, source_id, identity, title, tags, fetched_at)
                    VALUES (:id, :source, 'guid:old-1', 'Old news',
                            '[]', '2026-11-16 12:00:00')
                """), {"id": str(uuid4()), "source": str(uuid4())})

            await create_schema(engine)
            articles = await SqliteRepository(sessions(engine)).list_articles()
            assert len(articles) == 1
            assert articles[0].title == "Old news"
            assert articles[0].content is None
            # Idempotence: calling startup schema initialization twice is safe.
            await create_schema(engine)
            assert len(await SqliteRepository(sessions(engine)).list_articles()) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())



def test_existing_user_table_gains_synonyms_without_losing_profiles(tmp_path):
    """Add the user setting to an older SQLite file without resetting users."""
    from sqlalchemy import text

    async def scenario():
        engine = sqlite_engine(tmp_path / "legacy_users.db")
        old_id = str(uuid4())
        try:
            async with engine.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE users (
                        id VARCHAR(36) PRIMARY KEY,
                        name VARCHAR(100) NOT NULL UNIQUE,
                        created_at DATETIME,
                        config_version INTEGER NOT NULL
                    )
                """))
                await conn.execute(
                    text("""INSERT INTO users (id, name, created_at, config_version)
                            VALUES (:id, 'Legacy', '2026-11-22 12:00:00', 1)"""),
                    {"id": old_id},
                )
            await create_schema(engine)
            repo = SqliteRepository(sessions(engine))
            config = await repo.get_user_config(UUID(old_id))
            assert config.add_synonyms is False
            assert len(await repo.list_users()) == 1
            await create_schema(engine)
        finally:
            await engine.dispose()

    asyncio.run(scenario())

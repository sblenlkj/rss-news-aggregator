"""Local Qdrant vector persistence and update checks (optional extra)."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytest.importorskip("qdrant_client")

from news_aggregator.adapters.outbound.qdrant_semantic import QdrantSemanticIndex
from news_aggregator.application.rss.models import Article


class FakeEmbedder:
    model_name = "test-vectors-2d"

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(tuple(texts))
        return [
            [1.0, 0.0] if "AI" in text else [0.0, 1.0]
            for text in texts
        ]


def article(text):
    return Article(
        id=uuid4(), source_id=uuid4(), title=text,
        fetched_at=datetime.now(UTC),
    )


def test_qdrant_indexes_at_ingestion_and_reuses_article_vectors(tmp_path):
    async def scenario():
        embedder = FakeEmbedder()
        index = QdrantSemanticIndex(
            embedder, path=tmp_path / "qdrant", collection="test_articles"
        )
        articles = [article("AI models"), article("Football results")]
        texts = tuple(a.search_text for a in articles)
        try:
            # Querying an empty collection must NOT trigger article indexing.
            assert await index.scores("AI query", articles) == {}
            assert embedder.calls == []

            await index.upsert_articles(articles)
            assert embedder.calls.count(texts) == 1
            await index.upsert_articles(articles)
            assert embedder.calls.count(texts) == 1
            result = await index.scores("AI query", articles)
            assert result[articles[0].id] > result[articles[1].id]
            await index.scores("AI query", articles)
            assert embedder.calls.count(texts) == 1
            assert embedder.calls.count(("AI query",)) == 2
        finally:
            index.close()

        reopened = QdrantSemanticIndex(
            embedder, path=tmp_path / "qdrant", collection="test_articles"
        )
        try:
            await reopened.upsert_articles(articles)
            result = await reopened.scores("AI query", articles)
            assert result[articles[0].id] > result[articles[1].id]
            assert embedder.calls.count(texts) == 1
        finally:
            reopened.close()

    asyncio.run(scenario())


def test_qdrant_clipped_document_fingerprint_is_stable(tmp_path):
    class ClippedEmbedder(FakeEmbedder):
        def prepare(self, text):
            return text[:10]

    async def scenario():
        embedder = ClippedEmbedder()
        index = QdrantSemanticIndex(
            embedder, path=tmp_path / "qdrant", collection="test_clipped"
        )
        original = article("AI models and some long additional text")
        changed = original.__class__(
            id=original.id, source_id=original.source_id,
            title="AI models and a completely different ending",
            fetched_at=original.fetched_at,
        )
        try:
            await index.upsert_articles([original])
            assert len(embedder.calls) == 1
            await index.upsert_articles([changed])
            # Same first 10 characters: the embedded input is identical.
            assert len(embedder.calls) == 1
        finally:
            index.close()

    asyncio.run(scenario())


def test_embedding_document_prioritizes_title_tags_summary_before_long_content(tmp_path):
    """Tags are included even when the article content exceeds max_chars."""
    class ShortEmbedder(FakeEmbedder):
        def prepare(self, text):
            return text[:80]

    from dataclasses import replace

    embedder = ShortEmbedder()
    index = QdrantSemanticIndex(
        embedder, path=tmp_path / "qdrant", collection="field_order"
    )
    original = article("Заголовок")
    rich = replace(
        original,
        tags=("искусственный интеллект", "авиация"),
        summary="Краткое описание",
        content="Основной текст " * 500,
    )
    try:
        prepared = index._prepared_text(rich)
        assert len(prepared) == 80
        assert prepared.startswith(
            "Заголовок\nискусственный интеллект авиация\nКраткое описание"
        )
        assert "Основной текст" in prepared
        assert len(rich.search_text) > len(prepared)
    finally:
        index.close()

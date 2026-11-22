"""Semantic and hybrid search tested without GigaChat credentials or network."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from news_aggregator.application.models.user import UserConfig
from news_aggregator.application.rss.models import Article
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter
from news_aggregator.application.search.service import SearchService


def test_semantic_date_filter_source_and_hybrid_reasoning():
    async def scenario():
        source = uuid4()
        old = Article(
            id=uuid4(), source_id=source, title="AI research old", summary="old",
            fetched_at=datetime.now(UTC) - timedelta(days=40),
        )
        a = Article(
            id=uuid4(), source_id=source, title="Языковая модель GPT", summary="Новая AI модель",
            fetched_at=datetime.now(UTC),
        )
        b = Article(
            id=uuid4(), source_id=source, title="Исследования transformers", summary="Другое NLP",
            fetched_at=datetime.now(UTC),
        )

        class Storage:
            async def list_articles(self, source_ids):
                assert source_ids == {source}
                return [old, a, b]

        class Semantic:
            class Embedder:
                model_name = "FakeEmbeddings"
            embedder = Embedder()

            async def scores(self, query, articles):
                assert query == "развитие искусственного интеллекта"
                return {article.id: ({a.id: 0.92, b.id: 0.7}.get(article.id, 0.1))
                        for article in articles}

        keyword = KeywordFilter(id=uuid4(), value="модель")
        semantic = SemanticFilter(
            id=uuid4(), value="развитие искусственного интеллекта",
            threshold=0.75,
        )
        config = UserConfig(source_ids=(source,), filters=(keyword, semantic))
        service = SearchService(Storage(), semantic=Semantic())
        cutoff = datetime.now(UTC).date()

        only_semantic = await service.search(config, mode="semantic", date_from=cutoff)
        assert only_semantic.total == 1
        assert only_semantic.items[0].article.id == a.id
        match = only_semantic.items[0].matches[0]
        assert match.filter_id == semantic.id
        assert match.score == 0.92
        assert match.threshold == 0.75
        assert match.model == "FakeEmbeddings"

        hybrid = await service.search(config, mode="hybrid", date_from=cutoff)
        assert hybrid.total >= 1
        result = next(x for x in hybrid.items if x.article.id == a.id)
        assert {m.filter_type for m in result.matches} == {"keyword", "semantic"}
        assert all(x.article.id != old.id for x in hybrid.items)

    asyncio.run(scenario())


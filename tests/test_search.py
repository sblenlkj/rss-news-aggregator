"""Keyword BM25 and filter composition; no model downloads or network."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from news_aggregator.application.models.user import UserConfig
from news_aggregator.application.rss.models import Article
from news_aggregator.application.search.keyword import BM25Search
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter
from news_aggregator.application.search.service import (
    SearchService,
    SemanticSearchUnavailable,
)


def article(title: str, summary: str, source_id=None) -> Article:
    return Article(
        id=uuid4(),
        source_id=source_id or uuid4(),
        title=title,
        summary=summary,
        fetched_at=datetime.now(UTC),
    )


def test_keyword_ranks_relevant_articles_and_provides_terms():
    docs = [
        article("Новая языковая модель", "Исследование нейросетей"),
        article("Новости спорта", "Результаты футбольного матча"),
    ]
    hits = BM25Search().search(docs, "модель")
    assert len(hits) == 1
    assert hits[0].article.id == docs[0].id
    assert hits[0].score > 0
    assert "модель" in hits[0].matched_terms


def test_optional_synonym_expansion():
    class Synonyms:
        def expand(self, words, *, candidates, limit):
            assert candidates == {"новая", "машина", "экология"}
            assert words == ["автомобиль"]
            assert limit == 5
            return ["машина"]

    doc = article("Новая машина", "Экология")
    hits = BM25Search(synonyms=Synonyms()).search([doc], "автомобиль")
    assert len(hits) == 1
    assert hits[0].expanded_terms == ("машина",)
    assert BM25Search().search([doc], "автомобиль") == []


def test_search_service_filters_sources_and_keeps_match_reasons():
    async def scenario():
        source_a, source_b = uuid4(), uuid4()
        one = article("AI language model", "research", source_a)
        two = article("AI language model", "research", source_b)

        class Storage:
            async def list_articles(self, source_ids):
                return [a for a in (one, two) if a.source_id in source_ids]

        service = SearchService(Storage())
        config = UserConfig(
            source_ids=(source_a,),
            filters=(KeywordFilter(id=uuid4(), value="AI"),),
        )
        response = await service.search(config)
        assert response.total == 1
        assert response.items[0].article.id == one.id
        assert response.items[0].matches[0].engine == "bm25"
        assert response.items[0].matches[0].filter_id == config.filters[0].id

        unsupported = UserConfig(
            source_ids=(source_a,),
            filters=(SemanticFilter(id=uuid4(), value="science"),),
        )
        with pytest.raises(SemanticSearchUnavailable):
            await service.search(unsupported, mode="semantic")

    asyncio.run(scenario())


def test_keyword_search_includes_full_feed_content_even_without_summary():
    news = Article(
        id=uuid4(),
        source_id=uuid4(),
        title="Short heading",
        summary=None,
        content="Улучшенные эмбеддинги для поиска новостей",
        fetched_at=datetime.now(UTC),
    )
    result = BM25Search().search([news], "эмбеддинги")
    assert len(result) == 1
    assert result[0].matched_terms == ("эмбеддинги",)



def test_user_synonyms_and_preview_are_corpus_scoped():
    class Synonyms:
        def preview(self, words, *, limit):
            assert words == ["автомобиль"]
            assert limit == 5
            return ["машина"]

        def expand(self, words, *, candidates, limit):
            assert "машина" in candidates
            assert words == ["автомобиль"]
            return ["машина"]

    class Storage:
        async def list_articles(self, source_ids):
            return [news] if news.source_id in source_ids else []

    async def scenario():
        service = SearchService(
            Storage(), keyword=BM25Search(synonyms=Synonyms())
        )
        suggestions = await service.expand_keywords(["автомобиль"])
        assert suggestions == {"автомобиль": ["машина"]}
        config = UserConfig(
            source_ids=(news.source_id,),
            filters=(KeywordFilter(id=uuid4(), value="автомобиль"),),
            add_synonyms=True,
        )
        response = await service.search(config)
        assert response.total == 1
        assert response.items[0].matches[0].expanded_terms == ("машина",)

    news = article("Новая машина", "Экология")
    asyncio.run(scenario())


def test_semantic_threshold_is_search_parameter_not_saved_filter():
    class Embedder:
        model_name = "Fake"

    class Index:
        embedder = Embedder()

        async def scores(self, text, articles):
            return {articles[0].id: 0.6}

    class Storage:
        async def list_articles(self, source_ids):
            return [news]

    async def scenario():
        service = SearchService(Storage(), semantic=Index())
        config = UserConfig(
            source_ids=(news.source_id,),
            filters=(SemanticFilter(id=uuid4(), value="технологии"),),
        )
        assert (await service.search(
            config, mode="semantic", semantic_threshold=0.7,
        )).total == 0
        assert (await service.search(
            config, mode="semantic", semantic_threshold=0.5,
        )).total == 1

    news = article("Новая нейросеть", "Технологии")
    asyncio.run(scenario())


def test_weighted_hybrid_rrf_changes_ranking_without_mixing_raw_scores():
    """A stronger semantic weight ranks the semantic-only hit above BM25-only."""
    source = uuid4()
    keyword_doc = article("космос", "ракета", source)
    semantic_doc = article("спорт", "футбол", source)

    class Storage:
        async def list_articles(self, source_ids):
            return [keyword_doc, semantic_doc]

    class Embedder:
        model_name = "Fake"

    class Index:
        embedder = Embedder()

        async def scores(self, text, articles):
            return {semantic_doc.id: 0.9, keyword_doc.id: 0.1}

    async def scenario():
        service = SearchService(Storage(), semantic=Index())
        config = UserConfig(
            source_ids=(source,),
            filters=(
                KeywordFilter(id=uuid4(), value="космос"),
                SemanticFilter(id=uuid4(), value="космос"),
            ),
        )
        semantic_first = await service.search(
            config, mode="hybrid", bm25_weight=0.4,
            semantic_weight=0.6, semantic_threshold=0.5,
        )
        assert [hit.article.id for hit in semantic_first.items] == [
            semantic_doc.id, keyword_doc.id,
        ]
        bm25_first = await service.search(
            config, mode="hybrid", bm25_weight=0.8,
            semantic_weight=0.2, semantic_threshold=0.5,
        )
        assert [hit.article.id for hit in bm25_first.items] == [
            keyword_doc.id, semantic_doc.id,
        ]
        with pytest.raises(ValueError, match="sum to 1"):
            await service.search(
                config, mode="hybrid",
                bm25_weight=0.3, semantic_weight=0.3,
            )

    asyncio.run(scenario())


def test_hybrid_engine_weights_not_multiplied_by_number_of_filters():
    source = uuid4()
    keyword_doc = article("наука технологии", "открытие", source)
    semantic_doc = article("спорт", "чемпионат", source)

    class Storage:
        async def list_articles(self, source_ids):
            return [keyword_doc, semantic_doc]

    class Embedder:
        model_name = "Fake"

    class Index:
        embedder = Embedder()

        async def scores(self, text, articles):
            return {semantic_doc.id: 0.9}

    async def scenario():
        service = SearchService(Storage(), semantic=Index())
        config = UserConfig(
            source_ids=(source,),
            filters=(
                KeywordFilter(id=uuid4(), value="наука"),
                KeywordFilter(id=uuid4(), value="технологии"),
                SemanticFilter(id=uuid4(), value="прогнозы"),
            ),
        )
        hits = await service.search(
            config, mode="hybrid", bm25_weight=0.4,
            semantic_weight=0.6, semantic_threshold=0.5,
        )
        assert hits.items[0].article.id == semantic_doc.id

    asyncio.run(scenario())


def test_keyword_mode_orders_by_actual_bm25_score_not_rrf_rank():
    source = uuid4()
    first = article("самолёт", "", source)
    second = article("автомобиль автомобиль автомобиль", "", source)

    class Storage:
        async def list_articles(self, ids):
            return [first, second]

    async def scenario():
        config = UserConfig(
            source_ids=(source,),
            filters=(
                KeywordFilter(id=uuid4(), value="самолёт"),
                KeywordFilter(id=uuid4(), value="автомобиль"),
            ),
        )
        result = await SearchService(Storage()).search(config, mode="keyword")
        assert result.total == 2
        assert result.items[0].article.id == second.id
        assert result.items[0].ranking_score > result.items[1].ranking_score
        assert all(hit.ranking_method == "bm25" for hit in result.items)
        assert result.items[0].ranking_score == pytest.approx(
            sum(match.score for match in result.items[0].matches)
        )

    asyncio.run(scenario())

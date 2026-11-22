"""Russian morphology and corpus-restricted Navec expansion."""

from datetime import UTC, datetime
from uuid import uuid4

from news_aggregator.application.rss.models import Article
from news_aggregator.application.search.keyword import BM25Search
from news_aggregator.application.search.normalization import PymorphyNormalizer


def _article(title: str) -> Article:
    return Article(
        id=uuid4(),
        source_id=uuid4(),
        title=title,
        fetched_at=datetime.now(UTC),
    )


def test_lemma_matches_different_russian_forms():
    norm = PymorphyNormalizer()
    assert norm.tokenize("Нейросетями и нейросеть") == [
        "нейросеть", "и", "нейросеть"
    ]
    news = [_article("Исследователи работают с нейросетями")]
    results = BM25Search(normalizer=norm).search(news, "нейросеть")
    assert len(results) == 1
    assert "нейросеть" in results[0].matched_terms


def test_latin_model_terms_remain_searchable():
    norm = PymorphyNormalizer()
    assert "gpt" in norm.tokenize("GPT-4")
    assert BM25Search(normalizer=norm).search(
        [_article("GPT для новостей")], "gpt"
    )


def test_navec_candidate_restriction_and_similarity():
    import pytest
    np = pytest.importorskip("numpy")
    from news_aggregator.adapters.outbound.navec_synonyms import NavecSynonymProvider

    class FakeNavec:
        def __init__(self):
            self.data = {
                "автомобиль": np.array([1.0, 0.0]),
                "машина": np.array([0.98, 0.2]),
                "яблоко": np.array([0.0, 1.0]),
            }

        @property
        def vocab(self):
            class Vocab:
                words = ["автомобиль", "машина", "яблоко"]
            return Vocab()

        def __contains__(self, word):
            return word in self.data

        def __getitem__(self, word):
            return self.data[word]

    provider = NavecSynonymProvider(FakeNavec(), min_similarity=0.8)
    assert provider.expand(
        ["автомобиль"],
        candidates={"автомобиль", "машина", "яблоко", "помидор"},
        limit=2,
    ) == ["машина"]

    assert provider.preview(["автомобиль"], limit=2) == ["машина"]

    normalizer = PymorphyNormalizer()
    hits = BM25Search(
        normalizer=normalizer, synonyms=provider
    ).search([_article("Новая машина")], "автомобиль")
    assert len(hits) == 1
    assert hits[0].expanded_terms == ("машина",)


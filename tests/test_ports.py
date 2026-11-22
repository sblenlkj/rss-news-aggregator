"""Smoke checks: each interface is imported from its owning feature."""

from news_aggregator.application.ports.storage import NewsStorage, UserStorage
from news_aggregator.application.ports.vector_index import VectorIndex
from news_aggregator.application.rss.ports import FeedReader, TestFeedPublisher
from news_aggregator.application.search.ports import SemanticIndex, TextEmbedder


def test_port_locations():
    assert NewsStorage.__name__ == "NewsStorage"
    assert UserStorage.__name__ == "UserStorage"
    assert VectorIndex.__name__ == "VectorIndex"
    assert FeedReader.__name__ == "FeedReader"
    assert TestFeedPublisher.__name__ == "TestFeedPublisher"
    assert SemanticIndex.__name__ == "SemanticIndex"
    assert TextEmbedder.__name__ == "TextEmbedder"

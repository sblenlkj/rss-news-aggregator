"""Semantic search interfaces, independent of GigaChat and Qdrant."""

from typing import Protocol
from uuid import UUID

from news_aggregator.application.rss.models import Article


class TextEmbedder(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class SemanticIndex(Protocol):
    async def scores(
        self, query: str, articles: list[Article]
    ) -> dict[UUID, float]: ...


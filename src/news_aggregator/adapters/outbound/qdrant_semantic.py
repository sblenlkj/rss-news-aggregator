"""Persistent Qdrant vector index: write at ingestion, query existing vectors.

Local Qdrant keeps SQLite connections thread-affine, so its synchronous calls
must stay on the application's event-loop thread (not asyncio.to_thread).
"""

import asyncio
import hashlib
from pathlib import Path
from uuid import UUID

from news_aggregator.application.rss.models import Article
from news_aggregator.application.search.ports import TextEmbedder
from news_aggregator.logger import get_logger

logger = get_logger(__name__)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class QdrantSemanticIndex:
    def __init__(
        self,
        embedder: TextEmbedder, *,
        path: Path | None = None, url: str | None = None,
        collection: str = "rss_news", batch_size: int = 16,
    ):
        from qdrant_client import QdrantClient

        if (path is None) == (url is None):
            raise ValueError("Set either Qdrant local path or URL")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.embedder = embedder
        self.collection = collection
        self.batch_size = batch_size
        self._client = QdrantClient(url=url) if url else QdrantClient(path=str(path))
        self._lock = asyncio.Lock()
        logger.info(
            "Qdrant initialized collection=%s mode=%s",
            collection, "local" if path else "remote",
        )

    def close(self):
        self._client.close()
        logger.info("Qdrant closed collection=%s", self.collection)

    def _prepared_text(self, article: Article) -> str:
        """Put short, high-signal fields first before embedding truncation.

        BM25 still uses Article.search_text in full. RSS content stays intact
        in SQLite, even when only the first characters enter embeddings.
        """
        text = "\n".join(
            part for part in (
                article.title,
                " ".join(article.tags),
                article.summary,
                article.content,
            )
            if part
        )
        prepare = getattr(self.embedder, "prepare", None)
        return prepare(text) if prepare is not None else text

    async def upsert_articles(self, articles: list[Article]) -> None:
        """Compute embeddings only for missing/changed articles and persist them."""
        if not articles:
            return
        async with self._lock:
            await self._upsert_locked(articles)

    async def _upsert_locked(self, articles: list[Article]) -> None:
        from qdrant_client import models

        exists = self._client.collection_exists(self.collection)
        previous = {}
        if exists:
            for start in range(0, len(articles), self.batch_size):
                batch = articles[start : start + self.batch_size]
                rows = self._client.retrieve(
                    self.collection,
                    ids=[str(article.id) for article in batch],
                    with_payload=True,
                )
                previous.update({
                    str(row.id): row.payload or {} for row in rows
                })
        missing = [
            article for article in articles
            if previous.get(str(article.id), {}).get("fingerprint")
            != _fingerprint(self._prepared_text(article))
            or previous.get(str(article.id), {}).get("model")
            != self.embedder.model_name
        ]
        logger.info(
            "Qdrant ingestion candidates=%d missing_or_changed=%d",
            len(articles), len(missing),
        )
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            texts = [self._prepared_text(article) for article in batch]
            vectors = await self.embedder.embed(texts)
            if len(vectors) != len(batch):
                raise ValueError("Embedding count differs from article count")
            if not exists:
                self._client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(
                        size=len(vectors[0]), distance=models.Distance.COSINE,
                    ),
                )
                exists = True
            points = [
                models.PointStruct(
                    id=str(article.id),
                    vector=vector,
                    payload={
                        "source_id": str(article.source_id),
                        "fingerprint": _fingerprint(text),
                        "model": self.embedder.model_name,
                    },
                )
                for article, text, vector in zip(batch, texts, vectors)
            ]
            self._client.upsert(self.collection, points=points, wait=True)

    async def scores(self, query: str, articles: list[Article]) -> dict[UUID, float]:
        """Embed only the query; never re-embed RSS articles on search."""
        if not articles:
            return {}
        async with self._lock:
            if not self._client.collection_exists(self.collection):
                logger.info("Qdrant collection not indexed yet: %s", self.collection)
                return {}
            from qdrant_client import models

            embed_query = getattr(self.embedder, "embed_query", None)
            vector = (
                await embed_query(query) if embed_query is not None
                else (await self.embedder.embed([query]))[0]
            )
            response = self._client.query_points(
                self.collection,
                query=vector,
                limit=len(articles),
                query_filter=models.Filter(
                    must=[models.HasIdCondition(
                        has_id=[str(article.id) for article in articles]
                    )],
                ),
            )
            logger.info(
                "Qdrant query collection=%s candidates=%d hits=%d",
                self.collection, len(articles), len(response.points),
            )
            return {UUID(str(hit.id)): float(hit.score) for hit in response.points}

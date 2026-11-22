"""GigaChat embeddings through the supported LangChain integration.

Based on the connector pattern in sblenlkj/oil-gas-analyst.
The SDK handles OAuth and TLS options; no hand-written REST token lifecycle.
"""

import asyncio
from threading import Lock

from news_aggregator.logger import get_logger

logger = get_logger(__name__)


class GigaChatEmbedder:
    def __init__(
        self,
        authorization_key: str,
        *,
        model_name: str = "Embeddings",
        scope: str = "GIGACHAT_API_PERS",
        verify_ssl_certs: bool = True,
        max_chars: int = 2000,
        client=None,
    ):
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self.model_name = model_name
        self.max_chars = max_chars
        self._lock = Lock()
        if client is not None:
            self._embeddings = client
        else:
            from langchain_gigachat.embeddings import GigaChatEmbeddings

            self._embeddings = GigaChatEmbeddings(
                credentials=authorization_key.strip(),
                scope=scope,
                model=model_name or None,
                verify_ssl_certs=verify_ssl_certs,
            )

    def prepare(self, text: str) -> str:
        """Limit an embedding input, preserving the first part of the text."""
        return text[: self.max_chars]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return self._embeddings.embed_documents(texts)

    def _embed_query_sync(self, text: str) -> list[float]:
        with self._lock:
            return self._embeddings.embed_query(text)

    async def embed_query(self, text: str) -> list[float]:
        """Use SDK's dedicated query method, without touching article vectors."""
        return await asyncio.to_thread(self._embed_query_sync, self.prepare(text))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per input; SDK sync work runs off the event loop."""
        if not texts:
            return []
        prepared = [self.prepare(text) for text in texts]
        logger.info(
            "GigaChat embeddings requested model=%s texts=%d max_chars=%d",
            self.model_name, len(prepared), self.max_chars,
        )
        vectors = await asyncio.to_thread(self._embed_sync, prepared)
        if len(vectors) != len(prepared):
            raise ValueError("GigaChat returned an unexpected number of embeddings")
        return vectors

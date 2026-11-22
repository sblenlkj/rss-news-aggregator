"""GigaChat LangChain adapter and input clipping (no external requests)."""

import asyncio

from news_aggregator.adapters.outbound.gigachat_embeddings import GigaChatEmbedder


class FakeLangChainEmbeddings:
    def __init__(self):
        self.batches = []

    def embed_query(self, text):
        return [float(len(text)), 2.0]

    def embed_documents(self, texts):
        self.batches.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


def test_gigachat_adapter_clips_text_before_sdk_call():
    async def scenario():
        client = FakeLangChainEmbeddings()
        embedder = GigaChatEmbedder(
            "dummy-key", client=client, max_chars=10
        )
        assert embedder.prepare("абвгде12345") == "абвгде1234"
        vectors = await embedder.embed(["abcdefghijklmnopqrst", "short"])
        assert vectors == [[10.0, 1.0], [5.0, 1.0]]
        assert client.batches == [["abcdefghij", "short"]]
        assert await embedder.embed_query("long query string") == [10.0, 2.0]
        assert await embedder.embed([]) == []

    asyncio.run(scenario())

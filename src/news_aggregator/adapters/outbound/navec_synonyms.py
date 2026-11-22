"""Navec cosine-neighbor expansion restricted to the *current news corpus*.

Do not build a huge 500k-word nearest-neighbor index for a small RSS homework.
This provider compares query lemmas only with words present in search results.
The model is a word embedding source, not a guarantee of true synonyms.
"""

from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from navec import Navec


class NavecSynonymProvider:
    def __init__(
        self,
        model: "Navec",
        *,
        min_similarity: float = 0.55,
    ) -> None:
        if not -1 <= min_similarity <= 1:
            raise ValueError("min_similarity must lie in [-1, 1]")
        self._model = model
        self.min_similarity = min_similarity

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        min_similarity: float = 0.55,
    ) -> "NavecSynonymProvider":
        from navec import Navec

        return cls(Navec.load(str(path)), min_similarity=min_similarity)

    @cached_property
    def _preview_vectors(self) -> tuple[list[str], np.ndarray]:
        """Index frequent Navec vocabulary once, on first preview request.

        We intentionally cap at 50k words to keep memory/CPU modest.
        """
        words = [
            w for w in self._model.vocab.words[:50_000]
            if w not in {"<unk>", "<pad>"}
        ]
        terms: list[str] = []
        vectors: list[np.ndarray] = []
        for word in words:
            vector = np.asarray(self._model[word], dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if norm:
                terms.append(word)
                vectors.append(vector / norm)
        if not vectors:
            return [], np.empty((0, 0), dtype=np.float32)
        return terms, np.stack(vectors)

    def preview(self, words: list[str], *, limit: int = 5) -> list[str]:
        """Nearest vocabulary neighbors; independent of RSS subscriptions."""
        if not words or limit <= 0:
            return []
        terms, vectors = self._preview_vectors
        if not terms:
            return []
        ranked: dict[str, float] = {}
        originals = set(words)
        for word in dict.fromkeys(words):
            if word not in self._model:
                continue
            query = np.asarray(self._model[word], dtype=np.float32)
            norm = float(np.linalg.norm(query))
            if not norm:
                continue
            scores = vectors @ (query / norm)
            top = np.argsort(scores)[::-1][:limit + len(originals) + 10]
            for idx in top:
                term = terms[int(idx)]
                score = float(scores[idx])
                if term not in originals and score >= self.min_similarity:
                    ranked[term] = max(score, ranked.get(term, float("-inf")))
        return [
            term for term, _ in sorted(ranked.items(), key=lambda item: -item[1])[:limit]
        ]

    def expand(
        self,
        words: list[str],
        *,
        candidates: set[str],
        limit: int,
    ) -> list[str]:
        if limit <= 0 or not words or not candidates:
            return []

        candidates = set(candidates) - set(words)
        vectors = []
        terms = []
        for term in sorted(candidates):
            if term not in self._model:
                continue
            vec = np.asarray(self._model[term], dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                terms.append(term)
                vectors.append(vec / norm)
        if not vectors:
            return []

        matrix = np.stack(vectors)
        ranked: dict[str, float] = {}
        for word in dict.fromkeys(words):
            if word not in self._model:
                continue
            query = np.asarray(self._model[word], dtype=np.float32)
            qnorm = float(np.linalg.norm(query))
            if qnorm <= 0:
                continue
            scores = matrix @ (query / qnorm)
            for term, score in zip(terms, scores):
                value = float(score)
                if value >= self.min_similarity:
                    ranked[term] = max(value, ranked.get(term, float("-inf")))

        return [
            term for term, _ in sorted(
                ranked.items(), key=lambda pair: (-pair[1], pair[0])
            )[:limit]
        ]

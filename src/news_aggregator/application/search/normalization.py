"""Russian lemmatization for BM25, adapted from seminar-04 tokenizer ideas."""

import re
from functools import lru_cache

from pymorphy3 import MorphAnalyzer

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_RUSSIAN_RE = re.compile(r"^[а-яё]+$", re.IGNORECASE)


class PymorphyNormalizer:
    """Lemmatize Russian words; casefold other languages and numbers."""

    def __init__(self, morph: MorphAnalyzer | None = None) -> None:
        self._morph = morph or MorphAnalyzer()
        # Cache belongs to this instance instead of a class-level decorator
        # holding references to every normalizer ever constructed.
        self._lemma = lru_cache(maxsize=32768)(self._normalize_token)

    def _normalize_token(self, token: str) -> str:
        if _RUSSIAN_RE.fullmatch(token):
            return self._morph.parse(token)[0].normal_form
        return token

    def tokenize(self, text: str) -> list[str]:
        return [
            self._lemma(token.casefold())
            for token in _TOKEN_RE.findall(text)
        ]

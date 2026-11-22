"""Small seminar-inspired BM25 over RSS title, summary and tags.

Unlike the seminar's incremental EPUB index, this index is rebuilt from the
selected articles for each request. This is fine for a small homework corpus.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import log
from typing import Protocol

from news_aggregator.application.rss.models import Article

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


class TokenNormalizer(Protocol):
    def tokenize(self, text: str) -> list[str]: ...


class SimpleNormalizer:
    """Unicode-aware case-insensitive lexical baseline (no stemming)."""

    def tokenize(self, text: str) -> list[str]:
        return [word.casefold() for word in _TOKEN_RE.findall(text)]


class SynonymProvider(Protocol):
    def expand(
        self, words: list[str], *, candidates: set[str], limit: int
    ) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class KeywordHit:
    article: Article
    score: float
    matched_terms: tuple[str, ...]
    expanded_terms: tuple[str, ...]


class BM25Search:
    def __init__(
        self,
        normalizer: TokenNormalizer | None = None,
        synonyms: SynonymProvider | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.normalizer = normalizer or SimpleNormalizer()
        self.synonyms = synonyms
        self.k1 = k1
        self.b = b

    def search(
        self,
        articles: Sequence[Article],
        query: str,
        *,
        add_synonyms: bool = True,
        synonym_limit: int = 5,
    ) -> list[KeywordHit]:
        if not query.strip() or not articles:
            return []
        original = list(dict.fromkeys(self.normalizer.tokenize(query)))
        if not original:
            return []
        documents = [self.normalizer.tokenize(a.search_text) for a in articles]
        candidates = {term for terms in documents for term in terms}
        additions = (
            self.synonyms.expand(
                original, candidates=candidates, limit=synonym_limit
            )
            if add_synonyms and self.synonyms
            else []
        )
        normalized_additions = [
            word for term in additions for word in self.normalizer.tokenize(term)
        ]
        expanded = tuple(
            word for word in dict.fromkeys(normalized_additions)
            if word not in original
        )
        query_terms = tuple(original) + expanded
        doc_freq = Counter(
            term for terms in documents for term in set(terms)
        )
        n = len(documents)
        avg_length = sum(map(len, documents)) / n or 1.0
        results = []

        for article, terms in zip(articles, documents):
            counts = Counter(terms)
            score = 0.0
            matched = []
            for term in query_terms:
                tf = counts[term]
                if not tf:
                    continue
                matched.append(term)
                df = doc_freq[term]
                idf = log(1.0 + (n - df + 0.5) / (df + 0.5))
                norm = self.k1 * (
                    1.0 - self.b + self.b * (len(terms) / avg_length)
                )
                score += idf * tf * (self.k1 + 1.0) / (tf + norm)
            if score > 0:
                results.append(KeywordHit(
                    article=article,
                    score=score,
                    matched_terms=tuple(matched),
                    expanded_terms=tuple(w for w in expanded if w in matched),
                ))
        return sorted(results, key=lambda r: r.score, reverse=True)


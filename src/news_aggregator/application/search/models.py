"""Search filters and explainable result values."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from news_aggregator.application.rss.models import Article


@dataclass(frozen=True, slots=True)
class KeywordFilter:
    id: UUID
    value: str
    enabled: bool = True
    type: Literal["keyword"] = "keyword"


@dataclass(frozen=True, slots=True)
class SemanticFilter:
    id: UUID
    value: str
    enabled: bool = True
    threshold: float | None = None
    type: Literal["semantic"] = "semantic"


@dataclass(frozen=True, slots=True)
class SearchMatch:
    filter_id: UUID
    filter_type: str
    engine: str
    score: float | None = None
    matched_terms: tuple[str, ...] = ()
    expanded_terms: tuple[str, ...] = ()
    threshold: float | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    article: Article
    matches: tuple[SearchMatch, ...]
    ranking_score: float = 0.0
    ranking_method: Literal["bm25", "cosine", "weighted_rrf"] = "bm25"

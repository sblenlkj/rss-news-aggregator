"""Keyword, semantic and hybrid search with transparent match explanations."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from news_aggregator.application.models.user import UserConfig
from news_aggregator.application.ports.storage import NewsStorage
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter
from news_aggregator.application.search.ports import SemanticIndex
from news_aggregator.logger import get_logger

from .keyword import BM25Search
from .models import SearchHit, SearchMatch

logger = get_logger(__name__)


class SemanticSearchUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[SearchHit, ...]
    total: int
    limit: int
    offset: int


class SearchService:
    def __init__(
        self, storage: NewsStorage, keyword: BM25Search | None = None,
        semantic: SemanticIndex | None = None,
    ):
        self.storage = storage
        self.keyword = keyword or BM25Search()
        self.semantic = semantic

    async def expand_keywords(self, keywords: list[str]) -> dict[str, list[str]]:
        """Preview Navec vocabulary neighbors, without needing RSS articles."""
        if self.keyword.synonyms is None:
            raise SemanticSearchUnavailable("Navec is not configured")
        suggestions = {}
        for phrase in keywords:
            original = self.keyword.normalizer.tokenize(phrase)
            suggestions[phrase] = self.keyword.synonyms.preview(
                original, limit=5
            )
        logger.info("Navec vocabulary preview phrases=%d", len(keywords))
        return suggestions

    async def search(
        self, config: UserConfig, *, mode: str = "keyword",
        add_synonyms: bool = False, date_from: date | None = None,
        semantic_threshold: float | None = None,
        bm25_weight: float = 0.5, semantic_weight: float = 0.5,
        limit: int = 20, offset: int = 0,
    ) -> SearchPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        if semantic_threshold is not None and not -1 <= semantic_threshold <= 1:
            raise ValueError("Invalid semantic similarity threshold")
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("Unknown search mode")
        if not (0 <= bm25_weight <= 1 and 0 <= semantic_weight <= 1):
            raise ValueError("Hybrid weights must be between 0 and 1")
        if mode == "hybrid" and abs(bm25_weight + semantic_weight - 1.0) > 1e-6:
            raise ValueError("Hybrid weights must sum to 1")
        active = [f for f in config.filters if f.enabled]
        use_synonyms = config.add_synonyms or add_synonyms
        logger.info("Search started mode=%s sources=%d filters=%d synonyms=%s bm25_weight=%.2f semantic_weight=%.2f", mode, len(config.source_ids), len(active), use_synonyms, bm25_weight, semantic_weight)
        if not config.source_ids or not active:
            logger.info("Search skipped: no sources or enabled filters")
            return SearchPage((), 0, limit, offset)

        keyword_filters = [f for f in active if isinstance(f, KeywordFilter)]
        semantic_filters = [f for f in active if isinstance(f, SemanticFilter)]
        use_keyword = mode in ("keyword", "hybrid") and (mode != "hybrid" or bm25_weight > 0)
        use_semantic = mode in ("semantic", "hybrid") and (mode != "hybrid" or semantic_weight > 0)
        if use_semantic and semantic_filters and self.semantic is None:
            raise SemanticSearchUnavailable("Configure GigaChat Embeddings and Qdrant to enable semantic search")

        articles = await self.storage.list_articles(set(config.source_ids))
        if date_from:
            articles = [a for a in articles if a.fetched_at.date() >= date_from]
        logger.info("Search candidates=%d after source/date filtering", len(articles))
        by_id = {a.id: a for a in articles}
        matches = defaultdict(list)
        # Single-engine modes use their actual scores; hybrid uses weighted RRF.
        ranking_scores = defaultdict(float)
        ranking_method = {
            "keyword": "bm25", "semantic": "cosine", "hybrid": "weighted_rrf",
        }[mode]

        if use_keyword:
            for filt in keyword_filters:
                results = self.keyword.search(
                    articles, filt.value, add_synonyms=use_synonyms
                )
                logger.info("BM25 filter=%s matches=%d", filt.id, len(results))
                for rank, hit in enumerate(results, 1):
                    matches[hit.article.id].append(SearchMatch(
                        filter_id=filt.id, filter_type="keyword",
                        engine="bm25", score=hit.score,
                        matched_terms=hit.matched_terms,
                        expanded_terms=hit.expanded_terms,
                    ))
                    if mode == "hybrid":
                        ranking_scores[hit.article.id] += (
                            bm25_weight / len(keyword_filters) / (60 + rank)
                        )
                    else:
                        ranking_scores[hit.article.id] += hit.score

        if use_semantic and self.semantic is not None:
            for filt in semantic_filters:
                scores = await self.semantic.scores(filt.value, articles)
                threshold = (semantic_threshold if semantic_threshold is not None
                             else filt.threshold if filt.threshold is not None else 0.5)
                sorted_hits = sorted(
                    ((article_id, score) for article_id, score in scores.items()
                     if article_id in by_id and score >= threshold),
                    key=lambda item: -item[1],
                )
                logger.info("Semantic filter=%s matches=%d threshold=%.3f", filt.id, len(sorted_hits), threshold)
                for rank, (article_id, score) in enumerate(sorted_hits, 1):
                    matches[article_id].append(SearchMatch(
                        filter_id=filt.id, filter_type="semantic",
                        engine="cosine", score=score, threshold=threshold,
                        model=self.semantic.embedder.model_name,
                    ))
                    if mode == "hybrid":
                        ranking_scores[article_id] += (
                            semantic_weight / len(semantic_filters) / (60 + rank)
                        )
                    else:
                        ranking_scores[article_id] += score

        ordered_ids = sorted(
            matches, key=lambda i: (-ranking_scores[i], str(i))
        )
        logger.info("Search finished mode=%s total=%d returned=%d", mode, len(ordered_ids), len(ordered_ids[offset:offset + limit]))
        return SearchPage(
            items=tuple(
                SearchHit(
                    article=by_id[i], matches=tuple(matches[i]),
                    ranking_score=ranking_scores[i], ranking_method=ranking_method,
                )
                for i in ordered_ids[offset:offset + limit]
            ),
            total=len(matches), limit=limit, offset=offset,
        )


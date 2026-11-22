"""Request/response types at the HTTP boundary."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator

from news_aggregator.application.models.user import UserConfig
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UserRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime


class SourceCreate(BaseModel):
    url: HttpUrl


class SourceRead(BaseModel):
    id: UUID
    feed_url: str
    title: str
    is_active: bool
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None


class ArticleRead(BaseModel):
    id: UUID
    source_id: UUID
    title: str
    url: str | None
    external_id: str | None
    summary: str | None
    content: str | None
    tags: tuple[str, ...]
    published_at: datetime | None
    fetched_at: datetime


class KeywordFilterSchema(BaseModel):
    type: Literal["keyword"]
    value: str = Field(min_length=1)
    id: UUID = Field(default_factory=uuid4)
    enabled: bool = True


class SemanticFilterSchema(BaseModel):
    type: Literal["semantic"]
    value: str = Field(min_length=1)
    id: UUID = Field(default_factory=uuid4)
    enabled: bool = True
    threshold: float | None = Field(default=None, ge=-1, le=1)


FilterSchema = Annotated[
    KeywordFilterSchema | SemanticFilterSchema,
    Field(discriminator="type"),
]


class UserConfigSchema(BaseModel):
    source_ids: list[UUID] = Field(default_factory=list)
    filters: list[FilterSchema] = Field(default_factory=list)
    add_synonyms: bool = False

    def to_application(self) -> UserConfig:
        filters = []
        for item in self.filters:
            if isinstance(item, KeywordFilterSchema):
                filters.append(KeywordFilter(
                    id=item.id, value=item.value, enabled=item.enabled
                ))
            else:
                filters.append(SemanticFilter(
                    id=item.id, value=item.value, enabled=item.enabled,
                    threshold=item.threshold
                ))
        return UserConfig(
            source_ids=tuple(self.source_ids), filters=tuple(filters),
            add_synonyms=self.add_synonyms,
        )


class ExpandKeywordsRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=30)


class ExpandKeywordsResponse(BaseModel):
    suggestions: dict[str, list[str]]


class SearchRequestSchema(UserConfigSchema):
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword"
    semantic_threshold: float | None = Field(default=None, ge=-1, le=1)
    bm25_weight: float = Field(default=0.5, ge=0, le=1)
    semantic_weight: float = Field(default=0.5, ge=0, le=1)
    date_from: date | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_hybrid_weights(self):
        if self.mode == "hybrid" and abs(
            self.bm25_weight + self.semantic_weight - 1.0
        ) > 1e-6:
            raise ValueError("Hybrid BM25 and semantic weights must sum to 1")
        return self


class SearchMatchSchema(BaseModel):
    filter_id: UUID
    filter_type: str
    engine: str
    score: float | None
    matched_terms: tuple[str, ...]
    expanded_terms: tuple[str, ...]
    threshold: float | None = None
    model: str | None = None


class SearchHitSchema(BaseModel):
    article: ArticleRead
    matches: tuple[SearchMatchSchema, ...]
    ranking_score: float
    ranking_method: Literal["bm25", "cosine", "weighted_rrf"]


class SearchResponseSchema(BaseModel):
    items: tuple[SearchHitSchema, ...]
    total: int
    limit: int
    offset: int


class RefreshRead(BaseModel):
    source_id: UUID
    fetched: int
    upserted: int


class RefreshFailureRead(BaseModel):
    source_id: UUID
    error: str


class RefreshReportRead(BaseModel):
    successful: list[RefreshRead]
    failed: list[RefreshFailureRead]


class TestArticleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str = ""
    content: str | None = None
    tags: list[str] = Field(default_factory=list)


class TestArticleRead(BaseModel):
    id: UUID
    title: str
    summary: str
    content: str | None
    tags: tuple[str, ...]
    published_at: datetime


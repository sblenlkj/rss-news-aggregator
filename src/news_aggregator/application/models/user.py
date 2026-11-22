"""User and per-user subscription/filter configuration."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from news_aggregator.application.search.models import KeywordFilter, SemanticFilter


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UserConfig:
    source_ids: tuple[UUID, ...] = ()
    filters: tuple[KeywordFilter | SemanticFilter, ...] = ()
    add_synonyms: bool = False

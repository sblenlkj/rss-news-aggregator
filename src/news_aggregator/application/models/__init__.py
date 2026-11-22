"""Backward-compatible imports; canonical models live in their feature modules.

Prefer application.rss.models, application.search.models, application.user.
"""

from news_aggregator.application.models.user import User, UserConfig
from news_aggregator.application.rss.models import (
    Article,
    NewsSource,
    ParsedArticle,
    ParsedFeed,
    TestFeedEntry,
)
from news_aggregator.application.search.models import KeywordFilter, SemanticFilter

__all__ = [
    "Article",
    "KeywordFilter",
    "NewsSource",
    "ParsedArticle",
    "ParsedFeed",
    "SemanticFilter",
    "TestFeedEntry",
    "User",
    "UserConfig",
]

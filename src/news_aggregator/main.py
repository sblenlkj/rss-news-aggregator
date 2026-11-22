"""FastAPI entry point and service composition for the single-process MVP."""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from news_aggregator.adapters.outbound.persistence.database import (
    create_schema,
    sessions,
    sqlite_engine,
)
from news_aggregator.adapters.outbound.persistence.repository import SqliteRepository
from news_aggregator.adapters.rss import FeedparserReader
from news_aggregator.adapters.test_feed import FileTestFeedPublisher
from news_aggregator.api.routes import router
from news_aggregator.application.rss.bootstrap import (
    DEFAULT_RSS_URLS,
    bootstrap_sources,
)
from news_aggregator.application.rss.polling import poll_forever
from news_aggregator.application.rss.service import NewsAggregatorService
from news_aggregator.application.search.keyword import BM25Search
from news_aggregator.application.search.normalization import PymorphyNormalizer
from news_aggregator.application.search.service import SearchService
from news_aggregator.logger import get_logger, setup_logger

log = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    db_path: Path | None = None,
    *,
    reader=None,
    enable_polling: bool | None = None,
    poll_interval: float = 60.0,
    publisher_path: Path | None = None,
    semantic_index=None,
    enable_bootstrap: bool = True,
    bootstrap_urls: tuple[str, ...] = DEFAULT_RSS_URLS,
) -> FastAPI:
    """App factory; injected reader and disabled polling make HTTP tests deterministic."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    # An interval of 0 disables periodic polling; manual refresh still works.
    if enable_polling is None:
        poll_interval = float(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "0"))
        enable_polling = poll_interval > 0
    if poll_interval < 0:
        raise ValueError("NEWS_POLL_INTERVAL_SECONDS must be >= 0")
    if poll_interval == 0:
        enable_polling = False
    db_path = Path(db_path or os.environ.get(
        "NEWS_DB_PATH", PROJECT_ROOT / "data" / "news.db"
    ))
    publisher_path = Path(publisher_path or os.environ.get(
        "NEWS_TEST_FEED_PATH", PROJECT_ROOT / "data" / "test_feed.json"
    ))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logger(os.getenv("NEWS_LOG_LEVEL", "INFO"))
        log.info("Starting application db=%s polling=%s interval=%ss", db_path, enable_polling, poll_interval)
        engine = sqlite_engine(db_path)
        await create_schema(engine)
        repository = SqliteRepository(sessions(engine))
        stop = asyncio.Event()
        task = None
        app.state.repository = repository
        normalizer = PymorphyNormalizer()
        synonyms = None
        navec_path = os.environ.get("NEWS_NAVEC_PATH")
        if navec_path:
            weights_path = Path(navec_path)
            if not weights_path.is_absolute():
                weights_path = PROJECT_ROOT / weights_path
            if not weights_path.is_file():
                log.warning("Navec weights not found: %s", weights_path)
            else:
                try:
                    from news_aggregator.adapters.outbound.navec_synonyms import (
                        NavecSynonymProvider,
                    )
                except ImportError:
                    log.warning(
                        "Navec dependencies missing: run uv sync --extra semantic --extra synonyms"
                    )
                else:
                    synonyms = NavecSynonymProvider.from_path(weights_path)
                    log.info("Navec synonym expansion enabled: %s", weights_path)
        semantic = semantic_index
        if semantic is None and os.getenv("GIGACHAT_AUTH_KEY"):
            from news_aggregator.adapters.outbound.gigachat_embeddings import (
                GigaChatEmbedder,
            )
            from news_aggregator.adapters.outbound.qdrant_semantic import (
                QdrantSemanticIndex,
            )

            embedder = GigaChatEmbedder(
                os.environ["GIGACHAT_AUTH_KEY"],
                scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                model_name=os.getenv("GIGACHAT_EMBEDDING_MODEL", "Embeddings"),
                verify_ssl_certs=os.getenv(
                    "GIGACHAT_VERIFY_SSL_CERTS", "true"
                ).lower() in {"1", "true", "yes"},
                max_chars=int(os.getenv("NEWS_EMBED_MAX_CHARS", "2000")),
            )
            semantic = QdrantSemanticIndex(
                embedder, path=PROJECT_ROOT / "data" / "qdrant",
                collection="rss_" + embedder.model_name.lower().replace("-", "_"),
            )
        service = NewsAggregatorService(
            reader or FeedparserReader(), repository,
            vector_index=semantic if hasattr(semantic, "upsert_articles") else None,
        )
        app.state.service = service
        app.state.semantic_index = semantic
        app.state.search_service = SearchService(
            repository,
            keyword=BM25Search(normalizer=normalizer, synonyms=synonyms),
            semantic=semantic,
        )
        app.state.publisher = FileTestFeedPublisher(publisher_path)
        if enable_bootstrap:
            base_url = os.getenv(
                "NEWS_PUBLIC_BASE_URL", "http://127.0.0.1:8000"
            ).rstrip("/")
            await bootstrap_sources(
                repository,
                test_feed_url=base_url + "/test-feed/rss.xml",
                urls=bootstrap_urls,
            )
        log.info("Search initialized synonyms=%s semantic=%s", synonyms is not None, semantic is not None)
        try:
            if enable_polling:
                task = asyncio.create_task(poll_forever(service, stop, poll_interval))
                log.info("RSS poller started interval=%ss", poll_interval)
            else:
                log.info("RSS poller disabled; manual RSS refresh remains available")
            yield
        finally:
            stop.set()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if semantic is not None and semantic is not semantic_index:
                semantic.close()
            await engine.dispose()
            log.info("Application stopped")

    app = FastAPI(title="RSS News Aggregator", lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index_page():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/test-feed/rss.xml", include_in_schema=True)
    async def test_rss() -> Response:
        base_url = os.environ.get("NEWS_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
        return Response(
            content=app.state.publisher.render_xml(base_url),
            media_type="application/rss+xml",
        )

    return app


app = create_app()

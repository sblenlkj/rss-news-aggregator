"""JSON REST routes; all data access goes through the application ports."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from news_aggregator.application.search.service import SemanticSearchUnavailable
from news_aggregator.logger import get_logger

from .schemas import (
    ArticleRead,
    ExpandKeywordsRequest,
    ExpandKeywordsResponse,
    RefreshRead,
    RefreshReportRead,
    SearchRequestSchema,
    SearchResponseSchema,
    SourceCreate,
    SourceRead,
    TestArticleCreate,
    TestArticleRead,
    UserConfigSchema,
    UserCreate,
    UserRead,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


def _repo(request: Request):
    return request.app.state.repository


def _service(request: Request):
    return request.app.state.service


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/capabilities")
async def capabilities(request: Request):
    search = request.app.state.search_service
    return {
        "keyword": True,
        "synonyms_enabled": search.keyword.synonyms is not None,
        "semantic_enabled": search.semantic is not None,
        "semantic_model": (
            search.semantic.embedder.model_name if search.semantic else None
        ),
        "hybrid_method": "rrf",
    }


@router.get("/users", response_model=list[UserRead])
async def list_users(request: Request):
    return await _repo(request).list_users()


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(body: UserCreate, request: Request):
    logger.info("API create user requested")
    try:
        return await _repo(request).add_user(body.name)
    except IntegrityError as exc:
        raise HTTPException(409, "User name already exists") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(user_id: UUID, request: Request):
    try:
        return await _repo(request).get_user(user_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/users/{user_id}/config", response_model=UserConfigSchema)
async def get_config(user_id: UUID, request: Request):
    try:
        config = await _repo(request).get_user_config(user_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return asdict(config)


@router.put("/users/{user_id}/config", response_model=UserConfigSchema)
async def put_config(user_id: UUID, body: UserConfigSchema, request: Request):
    logger.info("API save user config user=%s sources=%d filters=%d", user_id, len(body.source_ids), len(body.filters))
    try:
        config = await _repo(request).save_user_config(
            user_id, body.to_application()
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return asdict(config)


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(request: Request):
    return await _repo(request).list_sources()


@router.post("/sources", response_model=SourceRead, status_code=201)
async def create_source(body: SourceCreate, request: Request):
    logger.info("API register RSS requested")
    try:
        return await _service(request).register_source(str(body.url))
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/sources/{source_id}/status", response_model=SourceRead)
async def source_status(source_id: UUID, request: Request):
    try:
        return await _repo(request).get_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: UUID, request: Request):
    try:
        await _repo(request).disable_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/search/expand", response_model=ExpandKeywordsResponse)
async def expand_keywords(body: ExpandKeywordsRequest, request: Request):
    """Preview corpus-specific Navec expansions without changing user filters."""
    keywords = [word.strip() for word in body.keywords if word.strip()]
    if not keywords:
        raise HTTPException(422, "Provide at least one keyword")
    try:
        suggestions = await request.app.state.search_service.expand_keywords(keywords)
    except SemanticSearchUnavailable as exc:
        raise HTTPException(501, str(exc)) from exc
    return ExpandKeywordsResponse(suggestions=suggestions)


@router.post("/search/index")
async def index_existing_articles(request: Request):
    """One-time backfill of vectors for articles already stored in SQLite."""
    index = request.app.state.semantic_index
    if index is None or not hasattr(index, "upsert_articles"):
        raise HTTPException(501, "Semantic vector index is not configured")
    articles = await _repo(request).list_articles()
    try:
        await index.upsert_articles(articles)
    except Exception as exc:
        logger.exception("Semantic index backfill failed")
        raise HTTPException(502, "Vector indexing failed; check server logs") from exc
    return {"checked": len(articles), "message": "Vector index synchronized"}


@router.post("/search", response_model=SearchResponseSchema)
async def search_articles(body: SearchRequestSchema, request: Request):
    logger.info("API search requested mode=%s filters=%d", body.mode, len(body.filters))
    try:
        return await request.app.state.search_service.search(
            body.to_application(), mode=body.mode, add_synonyms=body.add_synonyms,
            date_from=body.date_from, semantic_threshold=body.semantic_threshold,
            bm25_weight=body.bm25_weight, semantic_weight=body.semantic_weight,
            limit=body.limit, offset=body.offset
        )
    except SemanticSearchUnavailable as exc:
        raise HTTPException(501, str(exc)) from exc


@router.get("/articles", response_model=list[ArticleRead])
async def list_articles(request: Request, source_id: UUID | None = None):
    ids = {source_id} if source_id is not None else None
    return await _repo(request).list_articles(ids)


@router.post("/sources/{source_id}/refresh", response_model=RefreshRead)
async def refresh_one(source_id: UUID, request: Request):
    logger.info("API refresh RSS source=%s", source_id)
    try:
        return await _service(request).refresh_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        raise HTTPException(502, f"Could not refresh RSS source: {reason}") from exc


@router.post("/sources/refresh", response_model=RefreshReportRead)
async def refresh_all(request: Request):
    logger.info("API refresh all RSS sources")
    report = await _service(request).refresh_all_report()
    return {
        "successful": [asdict(item) for item in report.successful],
        "failed": [asdict(item) for item in report.failed],
    }


@router.post("/test-feed/articles", response_model=TestArticleRead, status_code=201)
async def publish_test_article(body: TestArticleCreate, request: Request):
    logger.info("API publish test RSS entry")
    return request.app.state.publisher.publish(
        title=body.title, summary=body.summary, tags=tuple(body.tags),
        content=body.content
    )

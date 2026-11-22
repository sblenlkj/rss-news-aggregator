## Обновление 22.11.2026 — модели, .env, API reference

- Модели разделены: `application/rss/models.py` (ParsedFeed, ParsedArticle, NewsSource, Article, TestFeedEntry), `application/search/models.py` (keyword/semantic фильтры и объясняемые результаты), `application/user.py` (User, UserConfig); `application/models.py` — только facade для совместимости.
- `python-dotenv` читает корневой `.env` автоматически при сборке FastAPI. `NEWS_NAVEC_PATH=models/navec_news.tar` разрешается относительно корня проекта; `GIGACHAT_AUTH_KEY` в `.env` пустой до ввода настоящего ключа.
- Для установки всех optional зависимостей **одновременно**: `uv sync --extra semantic --extra synonyms`, иначе `uv sync` удаляет отсутствующие в выбранных extras пакеты.
- Добавлен справочник реальных HTTP-маршрутов [api.md](api.md).
- Изменения не протестированы на Mac после рефакторинга; следующий шаг — прогон pytest/ruff и реальный запуск FastAPI.

---

## Обновление 21.11.2026 — RSS content и текущая ревизия

Перед погружением в историю решений читать [overview.md](overview.md), [rss.md](rss.md) и [search.md](search.md). RSS/Atom теперь сохраняет и индексирует `title + summary + content + tags`. Все текстовые поля допускают отсутствие; статья с одним title не падает. Поле `content` добавляется в существующую SQLite через небольшую аддитивную миграцию `create_schema`, без удаления данных. Тестовый RSS publisher теперь может отдавать `content:encoded`. Требуется локально выполнить тесты и проверить полный сценарий перед приёмкой.

---

## Обновление 16.11.2026 — семантика и статический UI

- Добавлены `TextEmbedder` и `SemanticIndex` в `application/search/ports.py` (ранее находились в общем `ports.py`).
- `adapters/outbound/gigachat_embeddings.py` — GigaChat OAuth + embeddings (требует реального Authorization Key и сертификатов); `adapters/outbound/qdrant_semantic.py` — локальный persistent Qdrant, доиндексация SQL-статей при поиске. `uv sync --extra semantic` включает qdrant-client.
- `application/search/service.py` — режимы `keyword`, `semantic`, `hybrid`; для hybrid RRF рангов BM25 + cosine, не cross-encoder reranker. `date_from` фильтрует по `fetched_at`, также действует фильтрация по выбранным RSS. `add_synonyms` включает опциональный Navec только в BM25.
- `src/news_aggregator/static/index.html`, `app.js`, `style.css` — одна длинная HTML-страница, открывается по `/`, API и assets с того же FastAPI.
- Тесты добавлены: `test_semantic.py`, `test_gigachat_embeddings.py` (mock HTTP), `test_qdrant_semantic.py` (optional extra). Реальные ключи/сеть не проверены; команды на Mac ещё не запускались.
- Следующие работы: проверить тесты/линтер, SSRF и локальную тестовую RSS-загрузку, настроить сертификаты и ключ, затем сквозную демонстрацию.

---

# План RSS News Aggregator — SQLite

**16.11.2026:** SQLAlchemy 2.x + SQLite (aiosqlite) — основное хранилище. Решение заменяет JSON storage. Основание: [условие](../hw2_task.md). Интерфейс: [frontend.md](frontend.md).

## Архитектура

- Корень Python-пакета: `src/news_aggregator` (не создаём `backend/`).
- `application/models.py` — модели Python (Article, ParsedArticle, NewsSource, User, UserConfig, KeywordFilter, SemanticFilter).
- `application/ports/storage.py` — общие `NewsStorage`, `UserStorage`; `application/ports/vector_index.py` — общий `VectorIndex`. RSS-специфичные `FeedReader`, `TestFeedPublisher` находятся в `application/rss/ports.py`, а семантические `TextEmbedder`, `SemanticIndex` — в `application/search/ports.py`.
- `application/rss/service.py` — регистрация RSS и refresh; `application/rss/polling.py` — цикл опроса 60 секунд, подключён в FastAPI lifespan.
- `application/search/keyword.py`, `normalization.py`, `models.py`, `service.py` — BM25 по title/summary/tags, русская лемматизация pymorphy3, OR фильтры, explainability. Navec расширение реализовано адаптером, включается только при наличии весов; semantic embeddings пока нет. Подробнее в [search.md](search.md).
- `adapters/rss.py` — HTTP RSS/Atom reader на feedparser/httpx.
- `adapters/outbound/persistence/models.py` — SQLAlchemy ORM.
- `adapters/outbound/persistence/database.py` — async engine, sessions, create_schema.
- `adapters/outbound/persistence/repository.py` — `SqliteRepository`: источники, статьи, пользователи и их настройки.
- `adapters/test_feed.py` — пока отдельный файловый publisher демонстрационного RSS. Его JSON — отдельная реализация тестового канала, НЕ основной news storage.
- `api/routes.py`, `api/schemas.py` и `main.py` созданы: FastAPI, SQLite startup, polling lifespan, `POST /search` (keyword + опциональная semantic) и статический UI.

Не нужны отдельные `domain/`, `backend/`, `ports/`, React/Vite. FastAPI будет раздавать и JSON REST API, и чистые HTML/CSS/JS на одном origin.

## SQL schema

| Таблица | Назначение |
| --- | --- |
| `users` | UUID id, unique name, created_at, config_version |
| `sources` | RSS URL, заголовок, активность, last_checked_at, last_success_at, last_error |
| `articles` | source_id FK, идентичность записи, title, summary, content, tags, published_at, fetched_at |
| `user_sources` | Составной PK user_id + source_id, персональные подписки |
| `filters` | Пользовательские keyword/semantic правила, enabled, threshold |

`UserConfig` хранится в двух связанных таблицах `user_sources` и `filters` с заменой в **одной транзакции**. Векторный индекс Qdrant добавим отдельно. Сначала без Alembic: создание таблиц через `create_schema`; изменение уже существующей схемы потребует миграций.

RSS-каналы общие на всех пользователей. Для поиска используем **title + summary + content + tags**, не скачиваем отдельные HTML-страницы. Оригинальный план ниже исторический; новое правило описано также в [rss.md](rss.md). При опросе используем RSS GUID, затем URL, затем хеш текста для дедупликации. Состояние проверки источника сохраняется в SQL. Запуск и затем периодические опросы каждые 60 секунд подключим к FastAPI lifecycle, а ручная refresh-ручка будет вызывать тот же service.

## API v1 (согласованные 15 endpoints)

Все JSON-ручки ниже под `/api/v1`, кроме XML GET:
- GET/POST `/users`
- GET `/users/{id}`; GET/PUT `/users/{id}/config`
- GET/POST `/sources`; DELETE `/sources/{id}`
- POST `/search`; GET `/articles`
- POST `/sources/{id}/refresh`; POST `/sources/refresh`; GET `/sources/{id}/status`
- GET `/test-feed/rss.xml` (прямой путь); POST `/test-feed/articles` (под API-префиксом)

Требования приёмки: keyword (6), semantic (8), multiuser (10), объяснения совпадений, публикация и повторная загрузка тестового RSS через обычный ingestion. См. исходное условие.

## Что готово и что далее

1. **Созданы файлы, тесты ещё не запускались:** SQLite ORM, async engine, repository и тест `tests/test_sqlite_repository.py`. RSS reader, test publisher, `NewsAggregatorService`, polling helper были созданы ранее.
2. **Проверка на Mac:** `uv sync`, `uv run pytest -q`, `uv run ruff check .`. Файловый MCP не умеет выполнять процессы.
3. Написано: FastAPI, dependency wiring через app.state, SQLite schema при старте, user/config/source/article endpoints, test-feed XML/publish, polling и ручной refresh. Добавлен `tests/test_api.py` с временной SQLite и fake feed reader. Локальные тесты ещё не выполнены.
4. BM25, `POST /search`, pymorphy3 и Navec-адаптер написаны; добавлены `tests/test_search.py` и `tests/test_morphology_synonyms.py`. Следующий этап — локальный запуск тестов, подключение весов Navec и semantic embeddings (см. [search.md](search.md)).
5. Semantic GigaChat + локальный Qdrant написаны; при поиске Qdrant догоняет SQL-статьи; необходимы реальный ключ и тестирование.
6. Статический HTML/CSS/JS UI написан; проверить браузер и полный сценарий приёмки.

## Legacy

`adapters/json_storage.py`, `tests/test_json_storage.py` и пустые `data/sources.json`, `data/articles.json` **оставлены без удаления** ради сохранения предыдущей работы. Их не подключать к новому приложению. Основная база будет `data/news.db` при настройке FastAPI. Тестовый RSS publisher пока хранит демонстрационные посты отдельно в JSON.

## Открытые ограничения

- При публичной регистрации RSS защитить от SSRF (проверка URL/IP/DNS, без небезопасных redirects). Reader сейчас имеет ограничения размера/времени, но полной проверки адреса ещё нет.
- SQLite обеспечивает транзакции SQL; Qdrant — внешний индекс без общей транзакции. При сбое нужен reindex/retry.
- Polling подключён в lifespan, но выполнение ещё не подтверждено. Рекомендуется один Uvicorn worker. `/search` поддерживает keyword, semantic и hybrid (RRF). Без GigaChat-конфигурации активные semantic фильтры дают HTTP 501. SSRF-защита регистрации внешнего RSS ещё необходима.
- Принимать RSS после длительного простоя можно только в пределах истории, доступной у издателя.

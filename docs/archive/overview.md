# RSS News Aggregator — карта проекта

Актуальная ревизия: 21.11.2026. Источник требований: [hw2_task.md](../hw2_task.md).
Код написан, но полный локальный прогон после последних правок **не подтверждён**.

## Зачем это приложение

Агрегатор регулярно читает RSS/Atom-каналы, сохраняет новости в SQLite и показывает пользователям только те новости, которые соответствуют их фильтрам. У каждого пользователя свои подписки на каналы и собственные keyword/semantic фильтры. Встроенный тестовый RSS нужен для демонстрации преподавателю: публикуем пост через страницу, затем загружаем его обычным RSS-парсером.

## Структура без избыточных слоёв

```text
src/news_aggregator/
├── application/
│   ├── models.py                  # совместимые старые импорты
│   ├── user.py                    # User / UserConfig
│   ├── ports/
│   │   ├── storage.py             # общие NewsStorage / UserStorage
│   │   └── vector_index.py        # общий контракт записи векторов
│   ├── rss/
│   │   ├── models.py              # ParsedFeed/ParsedArticle/Article/NewsSource/TestFeedEntry
│   │   ├── ports.py               # FeedReader / TestFeedPublisher
│   │   ├── service.py             # register_source / refresh_source / refresh_all
│   │   └── polling.py             # запуск обновлений каждые 60 секунд
│   └── search/
│       ├── models.py              # KeywordFilter/SemanticFilter/SearchHit/SearchMatch
│       ├── ports.py               # TextEmbedder / SemanticIndex
│       ├── keyword.py             # BM25
│       ├── normalization.py       # pymorphy3 (леммы)
│       ├── service.py             # keyword, semantic, hybrid RRF
│       └── models.py              # SearchHit / SearchMatch
├── adapters/
│   ├── rss.py                     # HTTP + feedparser, RSS/Atom -> ParsedFeed
│   ├── test_feed.py               # публикация собственных RSS-элементов в XML
│   └── outbound/
│       ├── persistence/           # SQLite/SQLAlchemy, статьи, источники, users
│       ├── navec_synonyms.py      # расширение терминов из Navec
│       ├── gigachat_embeddings.py # запрос в GigaChat API
│       └── qdrant_semantic.py     # локальные вектора и cosine поиск
├── api/                           # FastAPI маршруты и Pydantic HTTP-схемы
├── static/                        # одна страница HTML/CSS/JS
└── main.py                        # сборка зависимостей и FastAPI lifespan
```

Общие порты вынесены в `application/ports/`, узкие — в `rss/ports.py` и `search/ports.py`. Остальные файлы не надо механически перекладывать ради чистоты: достаточно двух логических областей `application/rss/` и `application/search/`.

## Цепочка RSS и сохранения

1. `POST /api/v1/sources` регистрирует URL в таблице `sources`.
2. `NewsAggregatorService.refresh_source` обращается к `FeedparserReader.fetch`.
3. `parse_feed` превращает RSS/Atom XML в `ParsedFeed` и `ParsedArticle`.
4. `SqliteRepository.save_articles` создаёт/обновляет строки в `articles` по `source_id + identity` (GUID → URL → хеш).
5. `poll_forever` повторяет загрузку примерно раз в 60 секунд, и есть ручная кнопка обновления. История статей сохраняется в SQLite после перезапуска.
6. Тестовый publisher живёт отдельно; его XML надо загрузить обычным reader, а не записывать пост непосредственно в `articles`.

Подробно: [rss.md](rss.md).

## Поисковые движки — что действительно написано

| Режим | Реализация | Условия |
| --- | --- | --- |
| Keyword | BM25 (`k1=1.5`, `b=0.75`); русская лемматизация через pymorphy3 | Работает без внешнего API; необходимо локально прогнать тесты |
| Расширение синонимами | Navec: cosine word vectors, до 5 похожих слов из словаря текущего корпуса, порог 0.55 | Нужны модель Navec на диске и optional `synonyms` extra |
| Semantic | GigaChat API делает embeddings для query и новостей, Qdrant хранит вектора и считает cosine | Нужны GigaChat credentials, optional `semantic` extra; реальные вызовы не проверены |
| Hybrid | Слияние рангов BM25 + cosine по RRF: сумма `1/(60+rank)` | Это **не** обученный reranker/cross-encoder |

Фильтры пользователя по нескольким фразам объединяются по OR; применяется фильтрация по выбранным RSS и нижней границе `Article.fetched_at`. Для каждого найденного `SearchHit` сохраняются причины: filter_id, engine, совпавшие/расширенные слова, score, а для семантики ещё model и threshold. Поле `search_text` сейчас собирается из **title + summary + content + tags**, без удаления одинаковых фрагментов.

Подробно: [search.md](search.md). Контракты HTTP и примеры запросов: [api.md](api.md).

## Где что хранится

- `data/news.db`: настоящая SQLite база, таблицы `users`, `sources`, `articles`, `user_sources`, `filters`.
- `data/qdrant/`: необязательный векторный индекс по UUID статей; переиндексация при изменении `search_text`.
- Тестовый RSS publisher: отдельный `data/test_feed.json`. Не путать с основным news-storage.
- `data/sources.json`, `data/articles.json` и `adapters/json_storage.py` — **legacy**, от прежней идеи хранения в JSON; не подключены к основной реализации.

## Что ещё требует проверки перед демонстрацией

- Запустить `uv sync --extra semantic --extra synonyms`, `uv run pytest -q`, `uv run ruff check .` на Mac и разобрать результаты. Все optional extras нужны совместно.
- Проверить реальные RSS-источники и собственный RSS: публикация → refresh → SQLite → поиск.
- Проверить приложение в браузере, создание двух пользователей, разные фильтры и сохранение конфигураций.
- Настроить ключ GigaChat и проверить Embeddings/Qdrant либо демонстрировать keyword-базу отдельно.
- Нужна надёжная защита от SSRF для произвольных RSS URL; текущий парсер ограничивает размер/время и запрещает redirects, но этого недостаточно для открытого сервиса.
- Новые столбцы SQLite создаются аддитивно при startup, однако полноценная система миграций не реализована.

## Минимальный запуск

```bash
uv sync --extra semantic --extra synonyms
uv run pytest -q
uv run ruff check .
uv run uvicorn news_aggregator.main:app --reload --port 8000
```

Страница: http://127.0.0.1:8000/; Swagger: http://127.0.0.1:8000/docs.

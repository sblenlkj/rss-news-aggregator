# RSS / Atom: формат, нормализация и хранение

Актуально на 22.11.2026. Это практическая памятка к `adapters/rss.py`, `application/rss/models.py` и SQLite repository, а не копия общей спецификации RSS.

## 1. Два уровня

- RSS 2.0: `<rss><channel> ... <item> ... </item></channel></rss>`. Канал содержит title, link, description. Item содержит поля отдельной новости.
- Atom: `<feed><entry> ... </entry></feed>`. `feedparser` приводит ключевые свойства обоих форматов к общей структуре `parsed.feed` / `parsed.entries`.

Поля могут отсутствовать, и это нормально. RSS-лента **не обязана** предоставлять полный текст веб-страницы. Мы берём только то, что реально есть в XML, и **не скачиваем отдельные HTML-страницы**.

## 2. Соответствие полей

| RSS 2.0 / Atom | Feedparser | Наша модель |
| --- | --- | --- |
| item title / entry title | `entry.title` | `title` |
| item description / entry summary | `entry.summary` | `summary` |
| RSS `content:encoded` / Atom content | `entry.content[].value` | `content` |
| item link / entry link | `entry.link` | `url` |
| item guid / entry id | `entry.id` | `external_id` |
| pubDate / published или updated | `published_parsed` / `updated_parsed` | `published_at` (UTC) |
| category / category | `entry.tags[].term` | `tags` |
| channel title / feed title | `parsed.feed.title` | `ParsedFeed.title` |

HTML-разметка в `summary` и `content` очищается `_plain_text`; итог — обычный поисковый текст. В случаях без title, но с текстом, используем отображаемый заголовок `(без заголовка)`. Пустые элементы без title/summary/content игнорируются.

## 3. Наши объекты

```python
@dataclass(frozen=True, slots=True)
class ParsedArticle:
    title: str
    url: str | None = None
    external_id: str | None = None
    summary: str | None = None
    content: str | None = None
    tags: tuple[str, ...] = ()
    published_at: datetime | None = None
```

`Article` наследует эти поля и добавляет `id: UUID`, `source_id: UUID`, `fetched_at: datetime`.

`ParsedFeed` содержит метаданные канала и `tuple[ParsedArticle, ...]`. `NewsSource` — зарегистрированный и сохраняемый в SQL источник, включая его status/last_checked/error.

## 4. Поисковый текст и индексация

`article.search_text` объединяет непустые поля `title`, `summary`, `content`, `tags`, именно в этом порядке **для BM25**. Для GigaChat текст формируется отдельно: `title → tags → summary → content` и обрезается до `NEWS_EMBED_MAX_CHARS` символов (по умолчанию 2000).

- Только `title`: статья корректна и доступна для поиска.
- `title + summary`: ищем по обоим.
- `title + content`: ищем по обоим.
- `title + summary + content`: сохраняем и индексируем все три. Если summary равен content, слова встречаются дважды; для нашего MVP это сознательное простое решение.
- Если контента нет, `content=None`, ничего не падает.

BM25 использует полное `search_text`; GigaChat embeddings — отдельную сборку этих же четырёх полей с приоритетом тегов перед длинным содержимым. Поскольку fingerprint Qdrant зависит от `search_text`, при обновлении статьи вектора могут быть пересчитаны.

## 5. Сохранение и дедупликация

`NewsAggregatorService.refresh_source` вызывает `FeedparserReader.fetch(url)`, затем `SqliteRepository.save_articles(source_id, feed.articles)`. В SQL есть UNIQUE(`source_id`, `identity`).

Identity выбирается по приоритету:
1. `guid` / `external_id`;
2. `url`;
3. SHA-256 от `search_text`, когда первые два отсутствуют.

При известном GUID сохраняем тот же внутренний UUID и обновляем title, summary, content и tags. При полностью идентичном тексте не записываем заново. Если нет ни GUID, ни URL, изменение текста порождает другую identity — известное ограничение fallback-хеша.

В уже существующей `data/news.db` столбца content могло не быть: `create_schema` при старте добавляет `articles.content TEXT` через безопасный аддитивный ALTER TABLE. **База не удаляется**. Старые статьи будут с `content=NULL`; при следующем успешном RSS-обновлении текст добавится, если сам канал ещё содержит эту публикацию.

## 6. Тестовый канал

`FileTestFeedPublisher` сохраняет тестовые посты в JSON, отдаёт их как реальный `/test-feed/rss.xml`. При публикации можно указать title, summary, content и tags. Полный текст выдаётся в стандартном namespace `content:encoded`. Приёмочный цикл: публикация → доступность XML → refresh этого RSS → SQL `articles` → поиск.

## 7. Проверяемые варианты

`tests/test_rss.py`:
- RSS title-only;
- title + description;
- title + content:encoded без summary;
- оба отдельных текста;
- одинаковые summary/content;
- Atom content;
- невалидный XML.

`tests/test_test_feed.py`: обратный путь publish → XML → parse_feed.

`tests/test_sqlite_repository.py`: запись/обновление content и аддитивное расширение старой SQLite.

После изменений тесты **не запускались** через подключённый файловый инструмент. Команда: `uv run pytest -q`; отдельно `uv run pytest tests/test_rss.py tests/test_test_feed.py tests/test_sqlite_repository.py -q`.

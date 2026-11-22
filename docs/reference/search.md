# Поиск: BM25, Navec, GigaChat и Qdrant

Актуальное устройство см. в `application/search/`, `adapters/outbound/` и `main.py`. Базовые сценарии проверены вручную в HTML-интерфейсе; точные scores и успешность сетевых вызовов зависят от текущего корпуса и внешнего GigaChat. HTTP-запросы — в [api.md](../api.md), состав RSS-статьи — в [rss.md](rss.md).

## Что индексируем

Одна новость = один документ. Поле `ParsedArticle.search_text` для BM25 собирается из непустых `title`, `summary`, `content`, `tags`. Для embeddings отдельно собираем `title`, `tags`, `summary`, `content` в таком порядке — затем применяем ограничение длины. Если `summary` и `content` совпадают, **оба учитываются**; это простое соглашение MVP. RSS предоставляет эти поля не всегда. Полный HTML статьи по ссылке не скачиваем.

Выбранные `source_ids` и `date_from` (по `fetched_at`, а не `published_at`) ограничивают кандидатов до поиска.

## Keyword search (работает без внешних API)

`application/search/normalization.py`: `PymorphyNormalizer` приводит русские слова к начальной форме (`pymorphy3`), остальные токены — к нижнему регистру. Английского stemmer пока нет.

`application/search/keyword.py`: BM25 по текущему набору кандидатов (`k1=1.5`, `b=0.75`, положительная сглаженная IDF). В выдаче `matched_terms` и BM25 score. При каждом запросе индекс для выбранного набора статей строится заново; для небольшого корпуса без отдельного inverted-index persistence это приемлемо.

### Расширение запроса Navec

`adapters/outbound/navec_synonyms.py` в BM25 выбирает близкие по косинусному сходству **слова** из словаря текущих RSS-новостей. Отдельный endpoint предпросмотра ищет по первым 50 тысячам слов частотного словаря Navec, без RSS-подписок; его результаты могут отличаться от фактического расширения запроса. По умолчанию порог 0.55 и максимум 5 расширений. Это не строгие словарные синонимы: слова могут быть тематически связаны, но не взаимозаменяемы. В ответе видны `expanded_terms`.

Архив `models/navec_news.tar` (~26.6 МБ) уже скачан и лежит локально; его не нужно распаковывать. В `.env`: `NEWS_NAVEC_PATH=models/navec_news.tar`. Navec и NumPy — основные зависимости (обычный `uv sync`).

## Semantic search: сохранённые embeddings

`adapters/outbound/gigachat_embeddings.py`: использует официальный пакет `langchain-gigachat` и класс `GigaChatEmbeddings` (паттерн из [oil-gas-analyst](https://github.com/sblenlkj/oil-gas-analyst/blob/main/src/oil_gas_analyst/capabilities/research/rag/adapters/gigachat_embeddings.py)). SDK отвечает за OAuth и HTTPS; синхронные методы SDK вызываются через `asyncio.to_thread` с `threading.Lock`.

`GIGACHAT_AUTH_KEY` — Authorization Key, `GIGACHAT_SCOPE=GIGACHAT_API_PERS`, `GIGACHAT_EMBEDDING_MODEL=Embeddings`, `GIGACHAT_VERIFY_SSL_CERTS=true`. При проблеме сертификата возможно установить `false` для локального теста, понимая риск отключённой TLS-проверки.

`NEWS_EMBED_MAX_CHARS=2000` (по умолчанию) ограничивает вход перед embeddings API; **в символах, не в токенах**. Для GigaChat используется `title → tags → summary → content`, чтобы теги не пропали при длинном содержимом. Целиком исходный `Article.search_text` по-прежнему участвует в BM25. Фактическая GigaChat-модель может иметь и другие лимиты; короткое ограничение — консервативная защита.

`adapters/outbound/qdrant_semantic.py`: Qdrant хранит векторы по UUID SQLite статьи, `fingerprint` (SHA-256 обрезанного текста) и имя модели. **Запись происходит при RSS refresh** для изменившихся статей. Индексация проверяет fingerprint и пропускает неизменённые записи. Запрос к Semantic выполняет только embedding текста запроса, затем ищет среди разрешённых UUID в Qdrant; он **не индексирует корпус заново**.

Для ранее накопленных статей можно выполнить отдельную команду из Swagger `POST /api/v1/search/index`, создающая отсутствующие векторы. При новом подключении GigaChat старые записи не индексируются на старте автоматически. Локальный Qdrant работает с синхронным клиентом в event loop для сохранения привязки SQLite connection к потоку; на небольшом домашнем корпусе приемлемо.

Фильтр `SemanticFilter` содержит текст и legacy-поле порога; для новых запросов порог cosine задаётся отдельным `semantic_threshold` (по умолчанию 0.5). При ошибке векторизации RSS-статьи остаются в SQLite; повторная индексация через `/search/index` восполнит пропущенные векторы.

## Порядок результатов и объяснения

- **Keyword:** итоговый `ranking_score` — сумма BM25 scores всех совпавших keyword-фильтров; сортировка по убыванию. Для одного фильтра итоговый score равен показанному BM25 score.
- **Semantic:** итоговый `ranking_score` — сумма cosine scores совпавших semantic-фильтров, сортировка по убыванию.
- **Hybrid:** итоговый `ranking_score` — взвешенный RRF (ниже), сортировка по убыванию.

Каждый `SearchHit` возвращает `ranking_score` и `ranking_method` (`bm25`, `cosine`, `weighted_rrf`), отдельно от `matches[].score`. Разные метрики не сравнивать по абсолютным значениям. Порядок считается **до** применения `offset`/`limit`.

## Hybrid (weighted RRF)

`application/search/service.py`: keyword и semantic фильтры дают наборы совпадений, объединяемые по OR. В гибридном режиме используется **Reciprocal Rank Fusion**:

```text
score_weighted_RRF(article) = sum(weight_engine / (60 + rank_engine))
```

Это объединение рангов двух сигналов, а **не** обученный cross-encoder или model2vec reranker. При `mode=hybrid` API принимает `bm25_weight` и `semantic_weight` от 0 до 1 с суммой 1 (default 0.5/0.5); UI использует 0.4/0.6. Веса умножаются на ранговый вклад; при нескольких фильтрах одного движка его вклад делится на количество активных фильтров этого движка, чтобы вес означал долю **сигнала**, а не долю каждого фильтра. Сырые BM25/cosine scores не складываются. Нулевой вес отключает соответствующую ветку. Для каждой найденной статьи возвращается `SearchHit`, содержащий `SearchMatch`: фильтр, движок, исходный BM25 или cosine score, термины / threshold / модель. Итоговый RRF score возвращается в `SearchHit.ranking_score` и отображается отдельно от исходных BM25/cosine scores.

## Как запустить все поисковые механизмы

```bash
uv sync
# Заполнить GIGACHAT_AUTH_KEY в корневом .env
uv run uvicorn news_aggregator.main:app --reload --port 8000
```

`GET /api/v1/capabilities` показывает, включены ли компоненты. Без GigaChat semantic и hybrid с активным semantic-фильтром возвращают 501; keyword остаётся рабочим.

## Что связано с семинаром преподавателя

В `../practice/nlp/sem-04-search/` были разобраны:
- токенизация + `pymorphy3`;
- inverted index + BM25;
- расширение запросов Navec;
- локальные SentenceTransformer/FRIDA embeddings + Qdrant;
- опциональный model2vec reranker.

Мы адаптировали идею BM25, лемматизации, Navec и Qdrant к RSS-статьям; вместо локальной FRIDA выбрали API GigaChat. Не скачиваем FRIDA или model2vec и не обучаем модель — для текущего MVP это необязательно.

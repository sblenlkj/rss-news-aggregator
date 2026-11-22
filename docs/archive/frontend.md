# Одностраничный интерфейс RSS News Studio

**Реализован код интерфейса:** `src/news_aggregator/static/index.html`, `style.css`, `app.js`; FastAPI отдаёт `/` и `/static/*`. Это **одна вертикально прокручиваемая страница**, без React/Node/Jinja. Нативные `fetch` запросы обращаются к тому же origin. **Код на Mac ещё не выполнялся**, поэтому поведение нужно проверить в браузере.

## Последовательность блоков

1. **RSS-источники**: список URL с последними статусами, добавление нового RSS, кнопка подключения собственного тестового RSS, обновление одного или всех источников; ниже раскрываемая форма создания тестовой RSS-новости (title, summary, tags). Статья попадает в общий `articles` только после обычной загрузки тестового RSS через сервис.
2. **Пользователи**: выпадающий список профилей и создание нового. Явное Load/Save пользовательской конфигурации; source subscriptions и фильтры хранятся в SQLite независимо для каждого пользователя.
3. **Настройки поиска**: несколько keyword-фраз (каждая строка — OR-фильтр), одна semantic-фраза, threshold cosine; выбор RSS источников, дата `date_from` по **`Article.fetched_at` (дата добавления в наше хранилище)**. Режим `keyword`, `semantic` или `hybrid`; чекбокс Navec включается только когда слова участвуют в ранжировании.
4. **Результаты**: карточки новостей, title со ссылкой, RSS-источник, дата добавления, summary/tags, список технических объяснений по каждому сработавшему фильтру — BM25 matched_terms/expanded_terms/score или semantic model/cosine/threshold.

`hybrid` — объединение BM25 и cosine по Reciprocal Rank Fusion (RRF, k=60) с объяснениями обоих сигналов, **не обученный cross-encoder reranker**. Имеется один главный search action; `POST /api/v1/search` не сохраняет конфигурацию. Сохранять можно отдельной кнопкой.

В API есть `GET /api/v1/capabilities`: страница показывает доступность Navec/GigaChat и отключает отсутствующие режимы. \n\nНиже сохраняется исторический набросок экранов, но решение выше имеет приоритет: отдельный `/admin` и `/feed` теперь **не планируем**.

---

# Browser UI concept — RSS News Aggregator

**Status:** proposed design, not implemented. Parent architecture: [plan.md](plan.md). Assignment: [../hw2_task.md](../hw2_task.md).

## Decision

Use **plain HTML, CSS and vanilla JavaScript** served by the **same FastAPI process** as the JSON REST API. No standalone frontend, React, Vite, Node/npm, SSR framework or template engine is needed for the MVP. The browser uses native `fetch()` and DOM events. This retains the backend's 15 agreed REST endpoints.

For implementation, keep `backend/src/news_aggregator/static/index.html`, `app.js` and `style.css` (create when working on UI), served by FastAPI. URLs:
- `/` — interactive news/configuration page.
- `/admin` — optional lightweight admin page or tab; can be combined with `/` to save time.
- `/docs` — FastAPI OpenAPI/Swagger for development, debugging and backup admin operations.
- `/api/v1/*` — existing REST API.
- `/test-feed/rss.xml` — actual test RSS feed.

Do **not** make Swagger the only UI for subscribing, creating users, configuring filters, or viewing personalized results. The 10-point acceptance requires a random student to operate the app easily.

## Main page: proposed visual structure

```text
┌──────────────────────────────────────────────────────────────┐
│ RSS News Aggregator                         [Admin] [Swagger]│
├───────────────────────┬──────────────────────────────────────┤
│ Profile               │ Filtered news                        │
│ [Choose user      ▼]  │                                      │
│ [+ Create user]       │ Article title / source / date        │
│ [Load configuration]  │ Snippet + original link              │
│                       │ Matched: keyword "transformer"       │
│ RSS subscriptions     │ Matched: semantic "AI", score 0.xx   │
│ [x] Source A          │                                      │
│ [x] Test RSS          │ Article title / ...                  │
│ [ ] Source B          │                                      │
│                       │                                      │
│ Keyword filters       │                                      │
│ [keyword            ] │                                      │
│ [+ Add keyword]       │                                      │
│                       │                                      │
│ Semantic topics       │                                      │
│ [topic              ] │                                      │
│ [threshold optional ] │                                      │
│ [+ Add topic]         │                                      │
│                       │                                      │
│ [Search] [Save config]│                                      │
└───────────────────────┴──────────────────────────────────────┘
```

Layout can be one column on narrow screens. Visual polish is secondary to legibility, clear labels and reliable interaction.

## Core interactions and API mapping

| User action | HTTP | Browser behavior |
| --- | --- | --- |
| Show user selector | `GET /api/v1/users` | Populate select |
| Create user | `POST /api/v1/users` | Add user and select it |
| Load saved setup | `GET /api/v1/users/{id}/config` | Replace **draft** form state with saved fields |
| Save setup | `PUT /api/v1/users/{id}/config` | Persist complete draft explicitly; show success/error |
| Show feed choices | `GET /api/v1/sources` | Populate checkboxes |
| Search with draft | `POST /api/v1/search` | Render matching articles and technical explanations, without implicit save |
| Browse ingested catalog | `GET /api/v1/articles` | Optional admin/diagnostics |
| Register source | `POST /api/v1/sources` | Admin form; refresh source choices |
| Refresh one/all | `POST /api/v1/sources/{id}/refresh`, `POST /api/v1/sources/refresh` | Admin controls; show progress/errors |
| Check source status | `GET /api/v1/sources/{id}/status` | Show last refresh details |
| Disable source | `DELETE /api/v1/sources/{id}` | Admin control with explicit confirmation |
| Publish test article | `POST /api/v1/test-feed/articles` | Admin/editor form, show published state; **not yet ingested** |

After publishing a test article, refresh the test source (or wait for scheduled polling) and then search again; only then should it appear in aggregated results. This avoids bypassing the actual RSS ingestion path.

## State and UX rules

- State in `app.js`: `selectedUserId`, `draftConfig`, `savedConfig` (optional comparison), `articles`, `loading/error`, current source catalog.
- Filters have client-side stable UUIDs; each has `type`, `value`, `enabled`; semantic filters additionally have optional `threshold`.
- A selected user has its own saved config; no cross-user mixing or auto-save.
- Distinguish `Search` from `Save configuration`. Draft edits may be searched without saving.
- Warn before switching users if draft has unsaved changes (or require explicit discard). Load is user initiated.
- Preserve and display which filter caused a hit, the engine, keyword match or semantic score/threshold when available. Do not fabricate similarity values.
- Show empty, loading, success, validation and network-error states. Avoid silent failures.
- Disable actions while their request is in flight to prevent duplicate submissions; use `textContent` for untrusted RSS content rather than unsafe `innerHTML`.
- Choose uncomplicated responsive CSS; accessible labels and keyboard-operable controls.
- No login/JWT unless explicitly required by the teacher; UI user selector is a profile switcher, not authorization.

## Admin surface

Keep admin lightweight. Two practical choices:
1. A second `admin.html` served by FastAPI with the same CSS/JS conventions.
2. An Admin tab/panel inside `index.html`, avoiding multiple pages.

Either option can use the same REST endpoints and needs no separate server. Swagger can handle diagnostics, but include user-friendly controls for adding RSS and publishing a test item, since both appear in the teacher's acceptance walkthrough.

## Implementation order

1. Build API first (domain, SQLite, application, RSS/search contracts).
2. Make a minimal static page that loads sources/users and calls `POST /search`.
3. Add editable filters/subscriptions, Save and Load, per-result explanations.
4. Add RSS admin controls and test-feed publication.
5. Check multi-user isolation and full instructor demo in a regular browser.
6. Improve CSS only if needed; no frontend tooling migration.

## Open decisions

- Whether `/admin` is a separate HTML page or a tab on `/`.
- Whether Search and saved Feed are the same view (preferred) or separate.
- Whether to poll for new articles periodically (and at what interval) or rely initially on manual refresh.
- UI appearance details, labels, error notification style and topic threshold defaults.

These are UX implementation choices, not blockers for backend bootstrap. Do not create UI files or backend scaffold solely from this document until implementation is requested.

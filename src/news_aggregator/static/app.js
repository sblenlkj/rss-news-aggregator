"use strict";

const el = (id) => document.getElementById(id);
const state = { sources: [], users: [], userId: "", saved: null, dirty: false };
const apiBase = "/api/v1";

async function api(path, options = {}) {
  const response = await fetch(apiBase + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = result.detail;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail || result);
    const error = new Error(`HTTP ${response.status}: ${message}`);
    error.status = response.status;
    throw error;
  }
  return result;
}

let feedbackOnClose = null;
function showFeedback(title, message, onClose = null) {
  feedbackOnClose = onClose;
  el("feedback-title").textContent = title;
  el("feedback-message").textContent = message;
  el("feedback-dialog").showModal();
}
function articleWord(count) {
  const n = Math.abs(count) % 100;
  const last = n % 10;
  return n >= 11 && n <= 14 ? "статей" :
    last === 1 ? "статья" : last >= 2 && last <= 4 ? "статьи" : "статей";
}
function notice(message, error = false) {
  el("notice").textContent = message;
  el("notice").classList.toggle("error", error);
}
async function run(button, action) {
  if (button) button.disabled = true;
  try { await action(); }
  catch (err) { console.error(err); notice(err.message || String(err), true); }
  finally { if (button) button.disabled = false; }
}
function element(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function fmtDate(value) {
  return value ? new Date(value).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" }) : "—";
}
function setDirty(value = true) {
  state.dirty = value;
  el("draft-indicator").textContent = value ? "Есть несохранённые изменения" : "Настройки сохранены";
}
function resetResults() {
  el("results").hidden = true;
  el("result-count").textContent = "—";
  el("results-list").replaceChildren();
}
function showUserSettings(visible) {
  el("profile-details").hidden = !visible;
  el("search").hidden = !visible;
  if (!visible) resetResults();
}
function updateSearchFields() {
  const mode = document.querySelector("input[name=mode]:checked").value;
  el("semantic-threshold-field").hidden = mode === "keyword";
  el("hybrid-weights").hidden = mode !== "hybrid";
}
function selectedSources() {
  return [...document.querySelectorAll("#subscription-list input:checked")].map(x => x.value);
}
function renderSubscriptions(selected = new Set(selectedSources())) {
  const box = el("subscription-list");
  box.replaceChildren();
  if (!state.sources.length) { box.append(element("p", "muted", "Нет подключённых RSS")); return; }
  for (const src of state.sources.filter(s => s.is_active)) {
    const label = element("label", "check");
    const input = element("input");
    input.type = "checkbox"; input.value = src.id; input.checked = selected.has(src.id);
    input.addEventListener("change", () => setDirty());
    label.append(input, element("span", "subscription-name", src.title || src.feed_url));
    box.append(label);
  }
}
function friendlyError(value) {
  if (/timeout/i.test(value)) return "сервер RSS не ответил вовремя (таймаут соединения)";
  if (/connecterror|connection refused|network error/i.test(value)) return "не удалось установить соединение с сервером RSS";
  if (/ssl|certificate/i.test(value)) return "ошибка TLS/сертификата при подключении";
  if (/429|too many requests/i.test(value)) return "сервер ограничил число запросов (HTTP 429)";
  if (/500|502|503|504/i.test(value)) return "сервер RSS временно недоступен";
  if (/301|302|redirect/i.test(value)) return "источник перенаправляет на другой URL";
  if (/403|forbidden/i.test(value)) return "доступ запрещён (HTTP 403)";
  if (/404|not found/i.test(value)) return "RSS не найден (HTTP 404)";
  return String(value).split("\n")[0].slice(0, 160);
}
function renderSources() {
  const box = el("source-list"); box.replaceChildren();
  if (!state.sources.length) { box.append(element("p", "muted", "Источников пока нет. Добавьте RSS-адрес.")); return; }
  for (const src of state.sources) {
    const row = element("div", "source-row");
    const info = element("div");
    info.append(element("div", "source-title", src.title || src.feed_url));
    const status = src.last_error ? "Ошибка обновления: " + friendlyError(src.last_error)
      : src.last_success_at ? "Успешно: " + fmtDate(src.last_success_at) : "Ещё не загружен";
    const statusEl = element("div", "source-meta " + (src.last_error ? "error-text" : "status"), status);
    if (src.last_error) statusEl.title = src.last_error;
    info.append(statusEl);
    const button = element("button", "button ghost", src.is_active ? "↻ Обновить" : "Отключён");
    button.disabled = !src.is_active;
    button.type = "button";
    button.addEventListener("click", () => run(button, async () => {
      let result;
      try {
        result = await api("/sources/" + src.id + "/refresh", { method: "POST" });
      } catch (error) {
        // A failed refresh is recorded in SourceRead.last_error by the backend.
        // Show it where the user clicked instead of a generic banner at the top.
        let details = error.message;
        try {
          await reloadSources();
          details = state.sources.find(item => item.id === src.id)?.last_error || details;
        } catch (reloadError) {
          console.warn("Could not reload source status", reloadError);
        }
        console.error("RSS refresh failed", error);
        notice("");
        const explanation = friendlyError(details);
        showFeedback("Не удалось обновить RSS",
          `Источник: ${src.title || src.feed_url}. Причина: ${explanation}. Проверьте подключение или повторите обновление позже.`);
        return;
      }
      await reloadSources();
      notice("");
      showFeedback("RSS обновлён",
        `Получено статей: ${result.fetched}. Новых или изменённых: ${result.upserted}.`);
    }));
    row.append(info, button); box.append(row);
  }
}
async function reloadSources() {
  const selected = new Set(selectedSources());
  state.sources = await api("/sources");
  renderSources();
  renderSubscriptions(selected);
}
async function reloadUsers() {
  state.users = await api("/users");
  const select = el("user-select"); const current = state.userId;
  select.replaceChildren(new Option("Выберите пользователя", ""));
  for (const u of state.users) select.add(new Option(u.name, u.id));
  select.value = current;
}
function configFromForm() {
  const old = state.saved?.filters || [];
  const keywords = el("keywords").value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const filters = keywords.map((value, index) => ({
    type: "keyword", value, enabled: true,
    id: old.filter(f => f.type === "keyword")[index]?.id || crypto.randomUUID(),
  }));
  const semantic = el("semantic-query").value.trim();
  if (semantic) filters.push({
    type: "semantic", value: semantic, enabled: true,
    id: old.find(f => f.type === "semantic")?.id || crypto.randomUUID(),

  });
  return { source_ids: selectedSources(), filters, add_synonyms: el("synonyms").checked };
}
function fillConfig(config) {
  el("keywords").value = (config.filters || []).filter(f => f.type === "keyword").map(f => f.value).join("\n");
  const semantic = (config.filters || []).find(f => f.type === "semantic");
  el("semantic-query").value = semantic?.value || "";
  el("synonyms").checked = Boolean(config.add_synonyms);
  el("expansion-status").textContent = "";
  renderSubscriptions(new Set(config.source_ids || []));
  setDirty(false);
}
async function loadConfig() {
  if (!state.userId) { notice("Сначала выберите пользователя.", true); return; }
  const userId = state.userId;
  const config = await api("/users/" + userId + "/config");
  if (state.userId !== userId) return;
  state.saved = config;
  fillConfig(config);
  showUserSettings(true);
}
async function createUser(event) {
  event.preventDefault();
  await run(el("new-user").querySelector("button"), async () => {
    const name = el("new-user-name").value.trim();
    let user;
    try {
      user = await api("/users", {
        method: "POST", body: JSON.stringify({ name }),
      });
    } catch (error) {
      if (error.status !== 409) throw error;
      el("user-conflict-message").textContent =
        `Пользователь «${name}» уже существует. Попробуйте другое имя.`;
      el("user-conflict-dialog").showModal();
      return;
    }
    state.userId = user.id;
    resetResults();
    await reloadUsers();
    el("new-user-name").value = "";
    await loadConfig();
    notice("Создан пользователь: " + user.name);
  });
}
async function saveConfig() {
  if (!state.userId) { notice("Выберите или создайте пользователя.", true); return; }
  await run(el("save-config"), async () => {
    const saved = await api("/users/" + state.userId + "/config", {
      method: "PUT", body: JSON.stringify(configFromForm()),
    });
    state.saved = saved; setDirty(false);
    notice("");
    showFeedback("Настройки сохранены", "Фильтры и RSS-подписки пользователя сохранены.");
  });
}
async function previewExpansion() {
  const keywords = el("keywords").value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  if (!keywords.length) {
    el("expansion-status").textContent = "Укажите хотя бы одно ключевое слово.";
    return;
  }
  await run(el("expand-keywords"), async () => {
    el("expansion-status").textContent = "Ищем близкие слова в словаре Navec…";
    const result = await api("/search/expand", {
      method: "POST",
      body: JSON.stringify({ keywords }),
    });
    const entries = Object.entries(result.suggestions)
      .map(([key, suggestions]) => key + ": " + (suggestions.length ? suggestions.join(", ") : "нет близких слов"));
    el("expansion-status").textContent = "Близкие слова из словаря Navec: " + entries.join(" · ") + ". При поиске расширение ограничивается словами из выбранных статей; фильтры не изменены.";
  });
}

async function doSearch() {
  if (!state.userId) { notice("Сначала выберите пользователя.", true); return; }
  const config = configFromForm();
  const mode = document.querySelector("input[name=mode]:checked").value;
  const keywords = config.filters.some(f => f.type === "keyword");
  const semantic = config.filters.some(f => f.type === "semantic");
  if (!config.source_ids.length) { notice("Отметьте хотя бы один RSS-источник.", true); return; }
  if ((mode === "keyword" && !keywords) || (mode === "semantic" && !semantic)
      || (mode === "hybrid" && (!keywords || !semantic))) {
    notice(mode === "hybrid"
      ? "Для гибридного поиска нужны и ключевые слова, и семантическая тема."
      : "Заполните поисковые фразы для выбранного режима.", true); return;
  }
  const limit = Number(el("search-limit").value);
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    notice("Лимит должен быть целым числом от 1 до 100.", true); return;
  }
  if (mode === "hybrid") {
    const bm25 = Number(el("bm25-weight").value);
    const embeddings = Number(el("semantic-weight").value);
    if (!Number.isFinite(bm25) || !Number.isFinite(embeddings)
        || bm25 < 0 || bm25 > 1 || embeddings < 0 || embeddings > 1
        || Math.abs(bm25 + embeddings - 1) > 1e-6) {
      notice("Веса BM25 и embeddings должны быть от 0 до 1, а сумма — ровно 1.", true);
      return;
    }
  }
  await run(el("search-button"), async () => {
    resetResults();
    notice("");
    const data = await api("/search", {
      method: "POST", body: JSON.stringify({
        ...config, mode,
        date_from: el("date-from").value || null,
        ...(mode !== "keyword" ? { semantic_threshold: Number(el("threshold").value) } : {}),
        ...(mode === "hybrid" ? {
          bm25_weight: Number(el("bm25-weight").value),
          semantic_weight: Number(el("semantic-weight").value),
        } : {}),
        limit, offset: 0,
      }),
    });
    renderResults(data);
    el("results").hidden = false;
    notice("");
    showFeedback("Поиск завершён",
      `Найдено ${data.total} ${articleWord(data.total)}. Режим: ${mode}.`,
      () => el("results").scrollIntoView({ behavior: "smooth" }));
  });
}
function addArticleField(card, label, value) {
  const block = element("div", "article-field");
  block.append(element("div", "article-field-label", label));
  const present = value !== null && value !== undefined && String(value).trim() !== "";
  block.append(element("div", present ? "article-field-text" : "article-field-empty",
    present ? String(value) : "Нет в RSS"));
  card.append(block);
}

function renderResults(data) {
  el("result-count").textContent = data.total + " " + articleWord(data.total);
  const box = el("results-list");
  box.replaceChildren();
  if (!data.items.length) {
    box.append(element("div", "empty", "Совпадений нет. Измените запрос, источники или дату."));
    return;
  }
  const lookup = Object.fromEntries(state.sources.map(s => [s.id, s.title]));
  for (const [index, hit] of data.items.entries()) {
    const a = hit.article;
    const card = element("article", "news");
    const header = element("div", "article-header");
    header.append(element("span", "article-rank", "#" + (data.offset + index + 1)));
    header.append(element("div", "source", lookup[a.source_id] || "RSS-источник"));
    card.append(header);
    const title = element("h3");
    if (a.url && /^https?:\/\//i.test(a.url)) {
      const link = element("a", "", a.title);
      link.href = a.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      title.append(link);
    } else {
      title.textContent = a.title;
    }
    card.append(title);
    const dates = element("div", "article-dates");
    dates.append(element("span", "", "Опубликовано: " + (a.published_at ? fmtDate(a.published_at) : "не указано в RSS")));
    dates.append(element("span", "", "Получено: " + fmtDate(a.fetched_at)));
    card.append(dates);
    addArticleField(card, "Summary · краткое описание", a.summary);
    addArticleField(card, "Content · полный текст RSS", a.content);
    addArticleField(card, "Теги", a.tags?.length ? a.tags.join(", ") : null);
    const reasons = element("div", "reasons");
    reasons.append(element("div", "article-field-label", "Почему новость найдена"));
    const scoreNames = {
      bm25: "BM25",
      cosine: "cosine",
      weighted_rrf: "взвешенный RRF",
    };
    const ranking = element("div", "ranking-score");
    ranking.textContent = "Итоговый score (" +
      (scoreNames[hit.ranking_method] || hit.ranking_method) + "): " +
      Number(hit.ranking_score).toFixed(hit.ranking_method === "weighted_rrf" ? 6 : 3);
    reasons.append(ranking);
    for (const m of hit.matches) {
      const reason = element("div", "reason");
      if (m.filter_type === "keyword") {
        const terms = m.matched_terms?.join(", ") || "—";
        const expanded = m.expanded_terms?.length
          ? "; похожие слова Navec: " + m.expanded_terms.join(", ") : "";
        reason.textContent = `BM25 · совпадение: ${terms}${expanded} · score: ${Number(m.score).toFixed(3)}`;
      } else {
        reason.textContent = `Semantic · ${m.model || "embedding"} · cosine: ${Number(m.score).toFixed(3)} · порог: ${m.threshold}`;
      }
      reasons.append(reason);
    }
    card.append(reasons);
    box.append(card);
  }
}

async function init() {
  showUserSettings(false);
  await Promise.all([reloadSources(), reloadUsers()]);
  const capabilities = await api("/capabilities");
  el("synonyms").disabled = !capabilities.synonyms_enabled;
  el("expand-keywords").disabled = !capabilities.synonyms_enabled;
  const unavailable = !capabilities.semantic_enabled;
  document.querySelectorAll("input[name=mode]").forEach(input => {
    if (input.value !== "keyword") input.disabled = unavailable;
  });
  el("capability-status").textContent = [
    capabilities.synonyms_enabled ? "Navec: доступен" : "Navec: нужны веса NEWS_NAVEC_PATH",
    capabilities.semantic_enabled ? "Semantic: " + capabilities.semantic_model : "Semantic: нужен ключ GigaChat",
  ].join(" · ");
  el("add-source").addEventListener("submit", event => {
    event.preventDefault();
    run(el("add-source").querySelector("button"), async () => {
      const source = await api("/sources", {
        method: "POST", body: JSON.stringify({ url: el("rss-url").value.trim() }),
      });
      el("rss-url").value = "";
      await reloadSources();
      const selected = new Set(selectedSources()); selected.add(source.id);
      renderSubscriptions(selected); setDirty();
      notice("");
      showFeedback(source.last_error ? "RSS подключён с предупреждением" : "RSS подключён",
        source.last_error
          ? "Источник добавлен, но его не удалось загрузить: " + friendlyError(source.last_error)
          : "Новый RSS-источник добавлен и проверен.");
    });
  });
  el("refresh-all").addEventListener("click", () => run(el("refresh-all"), async () => {
    const report = await api("/sources/refresh", { method: "POST" });
    await reloadSources();
    const succeeded = report.successful;
    const failed = report.failed;
    const fetched = succeeded.reduce((n, item) => n + item.fetched, 0);
    const upserted = succeeded.reduce((n, item) => n + item.upserted, 0);
    const errors = failed.map(item => {
      const source = state.sources.find(s => s.id === item.source_id);
      return (source?.title || source?.feed_url || item.source_id) + ": " + friendlyError(item.error);
    });
    notice("");
    showFeedback(
      failed.length ? "Обновление RSS: есть ошибки" : "Обновление RSS завершено",
      `Успешно: ${succeeded.length}. Ошибок: ${failed.length}. Получено статей: ${fetched}. Новых или изменённых: ${upserted}.`
      + (errors.length ? "\nНе удалось обновить:\n" + errors.join("\n") : ""),
    );
  }));
  el("publish-form").addEventListener("submit", event => {
    event.preventDefault();
    el("publish-status").textContent = "Публикуем…";
    el("publish-status").classList.remove("error-text");
    run(el("publish-form").querySelector("button"), async () => {
      let published;
      try {
        published = await api("/test-feed/articles", {
          method: "POST", body: JSON.stringify({
            title: el("publish-title").value.trim(),
            summary: el("publish-summary").value.trim(),
            content: el("publish-content").value.trim() || null,
            tags: el("publish-tags").value.split(",").map(x => x.trim()).filter(Boolean),
          }),
        });
      } catch (err) {
        el("publish-status").textContent = "Не удалось опубликовать: " + (err.message || String(err));
        el("publish-status").classList.add("error-text");
        throw err;
      }
      el("publish-form").reset();
      el("publish-status").textContent = `✓ Опубликовано в тестовом RSS: «${published.title}». Теперь обновите RSS для загрузки в общую ленту.`;
      el("publish-status").classList.remove("error-text");
      notice("Новость опубликована в тестовом RSS. Обновите канал, чтобы она появилась в поиске.");
    });
  });
  el("feedback-ok").addEventListener("click", () => el("feedback-dialog").close());
  el("feedback-dialog").addEventListener("close", () => {
    const action = feedbackOnClose;
    feedbackOnClose = null;
    if (action) action();
  });
  el("new-user").addEventListener("submit", createUser);
  el("user-conflict-ok").addEventListener("click", () => {
    el("user-conflict-dialog").close();
  });
  el("user-conflict-dialog").addEventListener("close", () => {
    el("new-user-name").focus();
    el("new-user-name").select();
  });
  el("user-select").addEventListener("change", async event => {
    if (state.dirty && !confirm("Черновик изменён. Перейти без сохранения?")) {
      event.target.value = state.userId; return;
    }
    state.userId = event.target.value;
    showUserSettings(false);
    state.saved = null;
    if (state.userId) await run(null, loadConfig);
    else { fillConfig({ source_ids: [], filters: [], add_synonyms: false }); }
  });
  el("save-config").addEventListener("click", saveConfig);
  el("select-all-sources").addEventListener("click", () => {
    const boxes = [...document.querySelectorAll("#subscription-list input[type=checkbox]")];
    const changed = boxes.some(box => !box.checked);
    boxes.forEach(box => { box.checked = true; });
    if (changed) setDirty();
  });
  document.querySelectorAll("input[name=mode]").forEach(input => {
    input.addEventListener("change", updateSearchFields);
  });
  for (const [edited, other] of [["bm25-weight", "semantic-weight"], ["semantic-weight", "bm25-weight"]]) {
    el(edited).addEventListener("input", () => {
      if (el(edited).value === "") return;
      const value = Number(el(edited).value);
      if (Number.isFinite(value) && value >= 0 && value <= 1) {
        el(other).value = Number((1 - value).toFixed(2)).toString();
      }
    });
  }
  updateSearchFields();
  el("search-button").addEventListener("click", doSearch);
  el("expand-keywords").addEventListener("click", previewExpansion);
  el("synonyms").addEventListener("change", () => { setDirty(); el("expansion-status").textContent = ""; });
  for (const id of ["keywords", "semantic-query"]) {
    el(id).addEventListener("input", () => setDirty());
  }
}
document.addEventListener("DOMContentLoaded", () => run(null, init));

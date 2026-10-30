/* ==========================================================================
   TU CSIT Notice Hub
   Fetches /api/notices, caches the last good payload, and filters client-side.

   Sections
     1. Elements + state
     2. Fetch + cache
     3. Formatting helpers
     4. Rendering (stats, chips, feed, states)
     5. Wiring
   ========================================================================== */

/* ------------------------------------------------------------------ dom */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const dom = {
  sync: $("#sync-state"),
  sourceBadge: $("#source-badge"),
  sourceText: $("#source-text"),
  refresh: $("#refresh"),
  refreshLabel: $("#refresh-label"),
  search: $("#search"),
  semester: $("#semester"),
  chips: $("#chips"),
  resultLine: $("#result-line"),
  reset: $("#reset"),
  banner: $("#banner"),
  bannerText: $("#banner-text"),
  feed: $("#feed"),
  pagination: $("#pagination"),
  pagePrevious: $("#page-previous"),
  pageNext: $("#page-next"),
  pageStatus: $("#page-status"),
  empty: $("#empty"),
  emptyReset: $("#empty-reset"),
  toast: $("#toast"),
  statTotal: $("#stat-total"),
  statExam: $("#stat-exam"),
  statResults: $("#stat-results"),
  statForms: $("#stat-forms"),
};

const CACHE_KEY = "tu-notice-hub:v1";
const CATEGORY_CLASS = {
  "Exam Routine": "exam",
  Results: "results",
  "Form Fill Up": "forms",
  "General Notice": "general",
};

const state = {
  notices: [],
  source: "loading",
  fetchedAt: null,
  error: null,
  stale: false,
  site: "",
  loading: false,
  query: "",
  semester: "all",
  category: "all",
  page: 1,
  total: 0,
  serverPaginated: false,
};
const PAGE_SIZE = 24;

/* ----------------------------------------------------------------- utils */

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.notices)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeCache(payload) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  } catch {
    /* storage may be full or blocked */
  }
}

function relativeTime(iso) {
  if (!iso) return "Undated";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "Undated";
  const diff = Date.now() - then.getTime();
  const day = 86_400_000;
  if (diff < 0) return "Just now";
  if (diff < day) {
    const hours = Math.max(1, Math.round(diff / 3_600_000));
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.round(diff / day);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.round(days / 30.4);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.round(months / 12);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

function formatDate(iso, fallback) {
  if (!iso) return fallback || "Undated";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return fallback || iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function formatSync(iso) {
  if (!iso) return "Not synced yet";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Not synced yet";
  const mins = Math.round((Date.now() - date.getTime()) / 60_000);
  if (mins < 1) return "Synced just now";
  if (mins < 60) return `Synced ${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `Synced ${hours} h ago`;
  return `Synced ${Math.round(hours / 24)} d ago`;
}

function toast(message) {
  dom.toast.textContent = message;
  dom.toast.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => dom.toast.classList.remove("is-visible"), 2600);
}

/* ----------------------------------------------------------------- fetch */
let feedRequestController = null;

async function fetchFeed({ force = false, silent = false } = {}) {
  if (feedRequestController) feedRequestController.abort();
  const controller = new AbortController();
  feedRequestController = controller;
  state.loading = true;
  dom.refresh.classList.add("is-busy");
  dom.refresh.disabled = true;
  if (!state.notices.length) dom.feed.setAttribute("aria-busy", "true");

  try {
    const params = new URLSearchParams({
      page: String(state.page),
      page_size: String(PAGE_SIZE),
    });
    if (state.category !== "all") params.set("category", state.category);
    if (state.semester !== "all") params.set("semester", state.semester);
    if (state.query.trim()) params.set("q", state.query.trim());
    const response = await fetch(`/api/notices?${params}`, {
      headers: { Accept: "application/json" },
      cache: "no-cache",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const incoming = Array.isArray(payload.notices) ? payload.notices : [];
    state.total = Number.isFinite(payload.total) ? payload.total : incoming.length;
    state.serverPaginated = payload.source === "archive";
    const known = new Set(state.notices.map((notice) => notice.id));
    const fresh = state.notices.length ? incoming.filter((notice) => !known.has(notice.id)) : [];

    if (payload.source === "unavailable" && state.notices.length) {
      state.stale = true;
      state.error = payload.error || "The official IoST source did not respond.";
      renderBadge();
      renderBanner();
      if (force) toast("Source unavailable; keeping the last available notices");
      return;
    }

    state.notices = incoming;
    state.source = payload.source || "unavailable";
    state.site = payload.source_site || "";
    state.fetchedAt = payload.fetched_at || new Date().toISOString();
    state.error = payload.error || null;
    state.stale = false;
    writeCache({
      notices: state.notices,
      source: state.source,
      site: state.site,
      fetched_at: state.fetchedAt,
      error: state.error,
      total: state.total,
    });
    render();
    if (fresh.length && !silent) {
      toast(`${fresh.length} new notice${fresh.length === 1 ? "" : "s"} found`);
    } else if (force) {
      toast("Notice feed checked");
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    state.error = String(error.message || error);
    if (!state.notices.length) {
      const cached = readCache();
      if (cached) {
        state.notices = cached.notices;
        state.source = cached.source || "unavailable";
        state.site = cached.site || "";
        state.fetchedAt = cached.fetched_at || null;
      }
    }
    state.source = state.notices.length ? state.source : "unavailable";
    render();
    if (force) toast("Could not reach the feed, showing cached notices");
  } finally {
    if (feedRequestController === controller) {
      feedRequestController = null;
      state.loading = false;
      dom.refresh.classList.remove("is-busy");
      dom.refresh.disabled = false;
      dom.feed.setAttribute("aria-busy", "false");
      renderBadge();
    }
  }
}

/* --------------------------------------------------------------- filters */

function filtered() {
  const query = state.query.trim().toLowerCase();
  return state.notices.filter((notice) => {
    if (state.category !== "all" && notice.category !== state.category) return false;
    if (state.semester !== "all" && notice.semester !== state.semester) return false;
    if (!query) return true;
    const haystack = `${notice.title} ${notice.category} ${notice.semester}`.toLowerCase();
    return query.split(/\s+/).every((word) => haystack.includes(word));
  });
}

function isNew(notice) {
  if (!notice.publish_date) return false;
  const published = new Date(notice.publish_date).getTime();
  return Number.isFinite(published) && Date.now() - published < 14 * 86_400_000;
}

/* --------------------------------------------------------------- render */

function renderStats() {
  const totals = { exam: 0, results: 0, forms: 0 };
  for (const notice of state.notices) {
    if (notice.category === "Exam Routine") totals.exam += 1;
    else if (notice.category === "Results") totals.results += 1;
    else if (notice.category === "Form Fill Up") totals.forms += 1;
  }
  dom.statTotal.textContent = String(state.serverPaginated ? state.total : state.notices.length);
  dom.statExam.textContent = String(totals.exam);
  dom.statResults.textContent = String(totals.results);
  dom.statForms.textContent = String(totals.forms);
}

function renderChips() {
  const counts = { all: state.notices.length };
  for (const notice of state.notices) {
    counts[notice.category] = (counts[notice.category] || 0) + 1;
  }
  for (const chip of $$(".chip", dom.chips)) {
    const key = chip.dataset.category;
    const badge = chip.querySelector("[data-count]");
    if (badge) badge.textContent = String(counts[key] || 0);
    const active = state.category === key;
    chip.classList.toggle("is-active", active);
    chip.setAttribute("aria-pressed", String(active));
  }
}

function renderBadge() {
  const map = {
    archive: ["Archived", "archive"],
    live: ["Live preview", "live"],
    unavailable: ["Offline", "error"],
    loading: ["Checking", "loading"],
  };
  const [label, kind] = map[state.source] || map.loading;
  dom.sourceText.textContent = label;
  dom.sourceBadge.dataset.source = kind;
  dom.sourceBadge.title = state.site ? `Source: ${state.site}` : "Official IoST notices";
  dom.sync.textContent = state.loading
    ? "Checking…"
    : state.source === "archive"
      ? formatSync(state.fetchedAt)
      : state.source === "live"
        ? "Not archived on this deployment"
        : "Source status unavailable";
}

function renderBanner() {
  if (state.stale) {
    dom.banner.hidden = false;
    dom.bannerText.textContent = "The latest check failed. Showing the last available notices.";
  } else if (state.source === "live") {
    dom.banner.hidden = false;
    dom.bannerText.textContent =
      "Showing the current official listing. A persistent local archive is not configured for this deployment.";
  } else if (state.source === "unavailable") {
    dom.banner.hidden = false;
    dom.bannerText.textContent = state.error
      ? `Could not load official IoST notices. ${state.error}`
      : "The official IoST source is unavailable. Try checking again later.";
  } else {
    dom.banner.hidden = true;
    dom.bannerText.textContent = "";
  }
}

function isOfficialUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      ["iost.tu.edu.np", "portal.tu.edu.np"].includes(url.hostname);
  } catch {
    return false;
  }
}

function isLocalDocumentUrl(value, disposition) {
  return typeof value === "string" &&
    new RegExp(`^/api/document\\?attachment_id=\\d+&disposition=${disposition}$`).test(value);
}

function noticeCard(notice) {
  const article = document.createElement("article");
  article.className = "notice" + (notice.urgent ? " is-urgent" : "");

  const tags = document.createElement("div");
  tags.className = "notice__tags";

  const category = document.createElement("span");
  category.className = `tag tag--${CATEGORY_CLASS[notice.category] || "general"}`;
  category.textContent = notice.category || "Notice";
  tags.append(category);

  if (notice.semester && notice.semester !== "All Semesters") {
    const semester = document.createElement("span");
    semester.className = "tag";
    semester.textContent = notice.semester;
    tags.append(semester);
  }

  if (notice.urgent) {
    const urgent = document.createElement("span");
    urgent.className = "tag tag--urgent";
    urgent.textContent = "Urgent";
    tags.append(urgent);
  } else if (isNew(notice)) {
    const fresh = document.createElement("span");
    fresh.className = "tag tag--new";
    fresh.textContent = "New";
    tags.append(fresh);
  }

  const title = document.createElement("h2");
  title.className = "notice__title";
  if (isOfficialUrl(notice.url)) {
    const link = document.createElement("a");
    link.href = notice.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    link.textContent = notice.title;
    title.append(link);
  } else {
    title.textContent = notice.title;
  }

  const foot = document.createElement("div");
  foot.className = "notice__foot";

  const dateWrap = document.createElement("div");
  dateWrap.className = "notice__date";
  const date = document.createElement("strong");
  date.textContent = formatDate(notice.publish_date, notice.date_label);
  const relative = document.createElement("span");
  relative.textContent = relativeTime(notice.publish_date);
  dateWrap.append(date, relative);

  const actions = document.createElement("div");
  actions.className = "notice__actions";

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "icon-btn";
  copy.setAttribute("aria-label", "Copy notice link");
  copy.title = "Copy link";
  copy.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5H6a1 1 0 0 0-1 1v9"/></svg>';
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(notice.url);
      toast("Notice link copied");
    } catch {
      toast(notice.url);
    }
  });

  actions.append(copy);
  const savedAttachments = (notice.attachments || []).filter(
    (attachment) =>
      attachment.available &&
      isLocalDocumentUrl(attachment.view_url, "inline") &&
      isLocalDocumentUrl(attachment.download_url, "attachment"),
  );
  for (const attachment of savedAttachments) {
    const view = document.createElement("a");
    view.className = "btn btn--ghost document-action";
    view.href = attachment.view_url;
    view.target = "_blank";
    view.rel = "noreferrer noopener";
    view.textContent = "View PDF";
    view.setAttribute("aria-label", `View ${attachment.filename || "notice document"}`);

    const download = document.createElement("a");
    download.className = "btn btn--ghost document-action";
    download.href = attachment.download_url;
    download.textContent = "Download";
    download.setAttribute("aria-label", `Download ${attachment.filename || "notice document"}`);
    actions.append(view, download);
  }
  if (!savedAttachments.length && isOfficialUrl(notice.url)) {
    const open = document.createElement("a");
    open.className = "btn btn--ghost document-action";
    open.href = notice.url;
    open.target = "_blank";
    open.rel = "noreferrer noopener";
    open.textContent = "View official notice";
    actions.append(open);
  }
  foot.append(dateWrap, actions);
  article.append(tags, title, foot);
  return article;
}

function renderFeed() {
  const list = filtered();
  const hasFilters = Boolean(state.query.trim()) || state.semester !== "all" || state.category !== "all";
  const resultCount = state.serverPaginated ? state.total : list.length;
  const pageCount = Math.max(1, Math.ceil(resultCount / PAGE_SIZE));
  state.page = Math.min(state.page, pageCount);
  const start = state.serverPaginated ? 0 : (state.page - 1) * PAGE_SIZE;
  const visible = state.serverPaginated ? list : list.slice(start, start + PAGE_SIZE);

  dom.reset.hidden = !hasFilters;
  dom.empty.hidden = list.length > 0 || state.loading;
  dom.feed.hidden = list.length === 0;
  dom.pagination.hidden = resultCount <= PAGE_SIZE;
  dom.pagePrevious.disabled = state.page <= 1;
  dom.pageNext.disabled = state.page >= pageCount;
  dom.pageStatus.textContent = `Page ${state.page} of ${pageCount}`;

  if (!state.notices.length && state.loading) {
    dom.feed.replaceChildren(...Array.from({ length: 4 }, () => {
      const skeleton = document.createElement("article");
      skeleton.className = "notice is-skeleton";
      return skeleton;
    }));
    dom.resultLine.textContent = "Loading notices…";
    return;
  }

  if (!state.notices.length) {
    dom.resultLine.textContent = "No notices available";
    dom.feed.replaceChildren();
    return;
  }

  const rangeStart = resultCount ? (state.page - 1) * PAGE_SIZE + 1 : 0;
  const rangeEnd = Math.min((state.page - 1) * PAGE_SIZE + PAGE_SIZE, resultCount);
  dom.resultLine.textContent = hasFilters
    ? `Showing ${rangeStart}–${rangeEnd} of ${resultCount} matching notices`
    : `Showing ${rangeStart}–${rangeEnd} of ${resultCount} notices · newest first`;

  dom.feed.replaceChildren(...visible.map(noticeCard));
}

function render() {
  renderStats();
  renderChips();
  renderBadge();
  renderBanner();
  renderFeed();
}

/* ---------------------------------------------------------------- wiring */

dom.refresh.addEventListener("click", () => fetchFeed({ force: true }));

let searchTimer = null;
dom.search.addEventListener("input", (event) => {
  const value = event.target.value;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.query = value;
    state.page = 1;
    renderFeed();
    dom.resultLine.parentElement.scrollIntoView({ block: "nearest", behavior: "smooth" });
    fetchFeed({ silent: true });
  }, 120);
});

dom.semester.addEventListener("change", (event) => {
  state.semester = event.target.value;
  state.page = 1;
  renderFeed();
  fetchFeed({ silent: true });
});

dom.chips.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  state.category = chip.dataset.category;
  state.page = 1;
  renderChips();
  renderFeed();
  fetchFeed({ silent: true });
});

dom.pagePrevious.addEventListener("click", () => {
  state.page = Math.max(1, state.page - 1);
  if (state.serverPaginated) fetchFeed({ silent: true });
  else renderFeed();
});

dom.pageNext.addEventListener("click", () => {
  state.page += 1;
  if (state.serverPaginated) fetchFeed({ silent: true });
  else renderFeed();
});

function resetFilters() {
  state.query = "";
  state.semester = "all";
  state.category = "all";
  state.page = 1;
  dom.search.value = "";
  dom.semester.value = "all";
  render();
  fetchFeed({ silent: true });
}

dom.reset.addEventListener("click", resetFilters);
dom.emptyReset.addEventListener("click", resetFilters);

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== dom.search) {
    event.preventDefault();
    dom.search.focus();
  }
  if (event.key === "Escape" && document.activeElement === dom.search) {
    dom.search.value = "";
    state.query = "";
    state.page = 1;
    renderFeed();
    fetchFeed({ silent: true });
    dom.search.blur();
  }
});

window.addEventListener("online", () => fetchFeed({ silent: true }));

/* ------------------------------------------------------------------ boot */

function boot() {
  render();
  const cached = readCache();
  if (cached) {
    state.notices = cached.notices;
    state.source = cached.source || "unavailable";
    state.site = cached.site || "";
    state.fetchedAt = cached.fetched_at || null;
    state.error = cached.error || null;
    state.total = cached.total || cached.notices.length;
    state.serverPaginated = cached.source === "archive";
    render();
  }
  fetchFeed();
}

boot();

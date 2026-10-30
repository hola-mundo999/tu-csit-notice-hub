const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const dom = {
  menuToggle: $("#menu-toggle"),
  nav: $("#primary-nav"),
  refresh: $("#refresh"),
  refreshLabel: $("#refresh-label"),
  sourceBadge: $("#source-badge"),
  sourceText: $("#source-text"),
  sync: $("#sync-state"),
  search: $("#search"),
  searchForm: $("#search-form"),
  semester: $("#semester"),
  sort: $("#sort-order"),
  pageSize: $("#page-size"),
  chips: $("#chips"),
  reset: $("#reset"),
  banner: $("#banner"),
  bannerText: $("#banner-text"),
  resultLine: $("#result-line"),
  feed: $("#feed"),
  pagination: $("#pagination"),
  pagePrevious: $("#page-previous"),
  pageNext: $("#page-next"),
  pageStatus: $("#page-status"),
  empty: $("#empty"),
  emptyTitle: $("#empty h3"),
  emptyText: $("#empty p"),
  emptyReset: $("#empty-reset"),
  statTotal: $("#stat-total"),
  statExam: $("#stat-exam"),
  statResults: $("#stat-results"),
  statForms: $("#stat-forms"),
  statGeneral: $("#stat-general"),
  dialog: $("#document-dialog"),
  documentTitle: $("#document-title"),
  documentStatus: $("#document-status"),
  documentFrame: $("#document-frame"),
  documentDownload: $("#document-download"),
  documentOriginal: $("#document-original"),
  documentOpen: $("#document-open"),
  documentClose: $("#document-close"),
  toast: $("#toast"),
};

const CACHE_KEY = "tu-notice-hub:v2";
const PAGE_SIZES = new Set([12, 24, 48]);
const CATEGORY_CLASS = {
  "Exam Routine": "exam",
  Results: "results",
  "Form Fill Up": "forms",
  "General Notice": "general",
};
const emptySummary = () => ({
  total: 0,
  exam_routines: 0,
  results: 0,
  form_fill_ups: 0,
  general_notices: 0,
});

const state = {
  notices: [],
  summary: null,
  source: "loading",
  fetchedAt: null,
  syncStatus: null,
  error: null,
  stale: false,
  site: "",
  loading: false,
  query: "",
  semester: "all",
  category: "all",
  sort: "newest",
  page: 1,
  pageSize: 24,
  total: 0,
  serverPaginated: false,
};

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    return Array.isArray(cached.notices) ? cached : null;
  } catch {
    return null;
  }
}

function writeCache(payload) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  } catch {
    toast("Notices loaded, but this browser could not save a local copy.");
  }
}

function toast(message) {
  dom.toast.textContent = message;
  dom.toast.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => dom.toast.classList.remove("is-visible"), 3200);
}

function formatDate(value, fallback = "Date unavailable") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

function relativeDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days < 0) return "Recently published";
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return "";
}

function summaryForNotices(notices) {
  const summary = emptySummary();
  summary.total = notices.length;
  for (const notice of notices) {
    if (notice.category === "Exam Routine") summary.exam_routines += 1;
    else if (notice.category === "Results") summary.results += 1;
    else if (notice.category === "Form Fill Up") summary.form_fill_ups += 1;
    else summary.general_notices += 1;
  }
  return summary;
}

function normalizeSummary(candidate, notices, source) {
  const keys = Object.keys(emptySummary());
  if (candidate && keys.every((key) => Number.isSafeInteger(candidate[key]) && candidate[key] >= 0)) {
    return Object.fromEntries(keys.map((key) => [key, candidate[key]]));
  }
  return source === "live" ? summaryForNotices(notices) : null;
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

function isPdf(attachment) {
  return attachment.mime_type === "application/pdf" ||
    /\.pdf(?:$|[?#])/i.test(attachment.filename || attachment.url || "");
}

let activeRequest = null;
async function fetchFeed({ force = false, silent = false } = {}) {
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  state.loading = true;
  dom.refresh.disabled = true;
  dom.refresh.classList.add("is-busy");
  if (!state.notices.length) dom.feed.setAttribute("aria-busy", "true");

  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    sort: state.sort,
  });
  if (state.category !== "all") params.set("category", state.category);
  if (state.semester !== "all") params.set("semester", state.semester);
  if (state.query) params.set("q", state.query);

  try {
    const response = await fetch(`/api/notices?${params}`, {
      headers: { Accept: "application/json" },
      cache: "no-cache",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Notice request failed (HTTP ${response.status}).`);
    const payload = await response.json();
    if (!Array.isArray(payload.notices)) throw new Error("The notice API returned an invalid response.");

    if (payload.source === "unavailable" && state.notices.length) {
      state.stale = true;
      state.error = payload.error || "The official source is unavailable.";
      render();
      if (force) toast("Source unavailable. Showing the last available notices.");
      return;
    }

    const previousIds = new Set(state.notices.map((notice) => notice.id));
    const newNotices = payload.notices.filter((notice) => !previousIds.has(notice.id));
    state.notices = payload.notices;
    state.source = payload.source || "unavailable";
    state.site = payload.source_site || "";
    state.fetchedAt = payload.fetched_at || null;
    state.syncStatus = payload.sync_status || null;
    state.error = payload.error || null;
    state.stale = false;
    state.total = Number.isSafeInteger(payload.total) ? payload.total : payload.notices.length;
    state.serverPaginated = payload.pagination_mode === "server" || state.source === "archive";
    state.summary = normalizeSummary(payload.summary, payload.notices, state.source);

    const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
    if (state.page > pages) {
      state.page = pages;
      return fetchFeed({ silent: true });
    }

    writeCache({
      notices: state.notices,
      source: state.source,
      source_site: state.site,
      fetched_at: state.fetchedAt,
      sync_status: state.syncStatus,
      total: state.total,
      summary: state.summary,
    });
    render();
    if (force) toast("Notice feed checked.");
    else if (!silent && newNotices.length) {
      toast(`${newNotices.length} new notice${newNotices.length === 1 ? "" : "s"} found.`);
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    state.error = error.message || "The notice feed could not be reached.";
    if (!state.notices.length) {
      const cached = readCache();
      if (cached) {
        state.notices = cached.notices;
        state.source = cached.source || "unavailable";
        state.site = cached.source_site || "";
        state.fetchedAt = cached.fetched_at || null;
        state.syncStatus = cached.sync_status || null;
        state.total = cached.total || cached.notices.length;
        state.summary = normalizeSummary(cached.summary, cached.notices, cached.source);
        state.serverPaginated = cached.source === "archive";
      } else {
        state.source = "unavailable";
      }
      state.stale = Boolean(cached);
    } else {
      state.stale = true;
    }
    render();
    if (force) toast("Could not check for new notices.");
  } finally {
    if (activeRequest === controller) {
      activeRequest = null;
      state.loading = false;
      dom.refresh.disabled = false;
      dom.refresh.classList.remove("is-busy");
      dom.feed.setAttribute("aria-busy", "false");
      renderStatus();
      renderFeed();
    }
  }
}

function locallyFilteredNotices() {
  const query = state.query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return state.notices.filter((notice) => {
    if (state.category !== "all" && notice.category !== state.category) return false;
    if (state.semester !== "all" &&
        notice.semester !== state.semester &&
        notice.semester !== "All Semesters") return false;
    const haystack = [
      notice.title,
      notice.source_id,
      notice.id,
      notice.category,
      notice.semester,
    ].join(" ").toLocaleLowerCase();
    return query.every((term) => haystack.includes(term));
  });
}

function renderStats() {
  const summary = state.summary;
  const values = [
    [dom.statTotal, summary?.total],
    [dom.statExam, summary?.exam_routines],
    [dom.statResults, summary?.results],
    [dom.statForms, summary?.form_fill_ups],
    [dom.statGeneral, summary?.general_notices],
  ];
  for (const [element, value] of values) {
    element.textContent = Number.isSafeInteger(value) ? String(value) : "—";
  }
}

function renderCategories() {
  const summary = state.summary || {};
  const counts = {
    all: summary.total,
    "Exam Routine": summary.exam_routines,
    Results: summary.results,
    "Form Fill Up": summary.form_fill_ups,
    "General Notice": summary.general_notices,
  };
  for (const chip of $$(".category-chip", dom.chips)) {
    const category = chip.dataset.category;
    const count = chip.querySelector("[data-count]");
    if (count) count.textContent = Number.isSafeInteger(counts[category]) ? String(counts[category]) : "—";
    const active = state.category === category;
    chip.classList.toggle("is-active", active);
    chip.setAttribute("aria-pressed", String(active));
  }
}

function renderStatus() {
  const labels = {
    archive: ["Archived", "archive"],
    live: ["Live preview", "live"],
    unavailable: ["Source unavailable", "error"],
    loading: ["Checking source", "loading"],
  };
  const [label, source] = labels[state.source] || labels.loading;
  dom.sourceText.textContent = label;
  dom.sourceBadge.dataset.source = source;
  dom.sourceBadge.title = state.site ? `Source: ${state.site}` : "Official IoST notices";
  if (state.loading) dom.sync.textContent = "Checking the official source…";
  else if (state.stale) dom.sync.textContent = "Showing previously loaded notices";
  else if (state.source === "archive") {
    const lastSuccess = state.syncStatus?.last_successful_at;
    const syncState = state.syncStatus?.status;
    if (lastSuccess) dom.sync.textContent = `Last synced ${formatDate(lastSuccess)}`;
    else if (syncState === "not_configured") dom.sync.textContent = "Archive sync is not configured";
    else dom.sync.textContent = `Archive sync status: ${syncState || "unknown"}`;
  } else if (state.source === "live") {
    dom.sync.textContent = "Current official listing · not a persistent archive";
  } else {
    dom.sync.textContent = "Official source status unavailable";
  }
}

function renderBanner() {
  if (state.stale) {
    dom.banner.hidden = false;
    dom.bannerText.textContent = "The latest request failed. The notices shown are from the last successful response.";
  } else if (state.source === "live") {
    dom.banner.hidden = false;
    dom.bannerText.textContent = "This is a live preview of recent official notices. Durable archive storage and scheduled synchronization are not configured for this deployment.";
  } else if (state.source === "unavailable") {
    dom.banner.hidden = false;
    dom.bannerText.textContent = state.error
      ? `Could not load official IoST notices. ${state.error}`
      : "The official IoST source is unavailable. Try refreshing later.";
  } else {
    dom.banner.hidden = true;
    dom.bannerText.textContent = "";
  }
}

function addTag(parent, label, variant = "") {
  const tag = document.createElement("span");
  tag.className = `notice-tag${variant ? ` notice-tag--${variant}` : ""}`;
  tag.textContent = label;
  parent.append(tag);
}

function createIcon(pathContent) {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 20 20");
  icon.setAttribute("fill", "none");
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = pathContent;
  return icon;
}

function documentAttachments(notice) {
  return (Array.isArray(notice.attachments) ? notice.attachments : []).filter((attachment) => {
    const localAvailable = attachment.available &&
      isLocalDocumentUrl(attachment.view_url, "inline") &&
      isLocalDocumentUrl(attachment.download_url, "attachment");
    return localAvailable || isOfficialUrl(attachment.url);
  });
}

function noticeCard(notice) {
  const article = document.createElement("article");
  article.className = "notice-card";

  const main = document.createElement("div");
  main.className = "notice-card__main";
  const tags = document.createElement("div");
  tags.className = "notice-card__tags";
  addTag(tags, notice.category || "General Notice", CATEGORY_CLASS[notice.category] || "general");
  if (notice.semester && notice.semester !== "All Semesters") addTag(tags, notice.semester);

  const explicitlyUrgent = /\b(urgent|last date|deadline|due date)\b/i.test(notice.title || "");
  if (explicitlyUrgent) addTag(tags, "Time-sensitive", "urgent");
  else if (relativeDate(notice.publish_date) === "Today" ||
           relativeDate(notice.publish_date) === "Yesterday") {
    addTag(tags, "Recently published", "new");
  }

  const title = document.createElement("h3");
  title.className = "notice-card__title";
  if (isOfficialUrl(notice.url)) {
    const link = document.createElement("a");
    link.href = notice.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    link.textContent = notice.title || "Untitled notice";
    title.append(link);
  } else {
    title.textContent = notice.title || "Untitled notice";
  }

  const meta = document.createElement("div");
  meta.className = "notice-card__meta";
  const dateMeta = document.createElement("span");
  dateMeta.className = "notice-card__meta-item";
  dateMeta.append(createIcon('<rect x="3" y="4.5" width="14" height="12" rx="1.5"/><path d="M6.5 3v3M13.5 3v3M3 8h14"/>'));
  dateMeta.append(document.createTextNode(formatDate(notice.publish_date, notice.date_label || "Date unavailable")));
  meta.append(dateMeta);

  const sourceId = notice.source_id || (notice.id ? String(notice.id) : "");
  if (sourceId) {
    const separator = document.createElement("span");
    separator.className = "notice-card__meta-separator";
    separator.setAttribute("aria-hidden", "true");
    const idMeta = document.createElement("span");
    idMeta.className = "notice-card__meta-item";
    idMeta.textContent = `Notice ID ${sourceId}`;
    meta.append(separator, idMeta);
  }
  const relative = relativeDate(notice.publish_date);
  if (relative) {
    const separator = document.createElement("span");
    separator.className = "notice-card__meta-separator";
    separator.setAttribute("aria-hidden", "true");
    const relativeMeta = document.createElement("span");
    relativeMeta.className = "notice-card__meta-item";
    relativeMeta.textContent = relative;
    meta.append(separator, relativeMeta);
  }
  main.append(tags, title, meta);

  const actions = document.createElement("div");
  actions.className = "notice-card__actions";
  for (const attachment of documentAttachments(notice)) {
    const pdf = isPdf(attachment);
    const previewUrl = attachment.available ? attachment.view_url : attachment.url;
    const downloadUrl = attachment.available ? attachment.download_url : attachment.url;
    if (pdf) {
      const preview = document.createElement("button");
      preview.className = "button button--secondary";
      preview.type = "button";
      preview.textContent = "Preview PDF";
      preview.setAttribute("aria-label", `Preview ${attachment.filename || "notice PDF"}`);
      preview.dataset.previewUrl = previewUrl;
      preview.dataset.noticeUrl = isOfficialUrl(notice.url) ? notice.url : "";
      preview.dataset.filename = attachment.filename || "Notice PDF";
      preview.dataset.downloadUrl = downloadUrl;
      actions.append(preview);
    }
    const download = document.createElement("a");
    download.className = "button button--secondary";
    download.href = downloadUrl;
    download.textContent = "Download";
    download.setAttribute("aria-label", `Download ${attachment.filename || "notice document"}`);
    if (!attachment.available) {
      download.target = "_blank";
      download.rel = "noreferrer noopener";
    }
    actions.append(download);
  }

  if (isOfficialUrl(notice.url)) {
    const original = document.createElement("a");
    original.className = "button button--primary";
    original.href = notice.url;
    original.target = "_blank";
    original.rel = "noreferrer noopener";
    original.textContent = "Official notice";
    actions.append(original);
  }

  if (isOfficialUrl(notice.url)) {
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "icon-button";
    copy.setAttribute("aria-label", `Copy link to ${notice.title || "notice"}`);
    copy.title = "Copy official notice link";
    copy.append(createIcon('<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M13 7V4.5A1.5 1.5 0 0 0 11.5 3h-7A1.5 1.5 0 0 0 3 4.5v7A1.5 1.5 0 0 0 4.5 13H7"/>'));
    copy.addEventListener("click", () => copyNoticeLink(notice.url));
    actions.append(copy);
  }

  article.append(main, actions);
  return article;
}

async function copyNoticeLink(url) {
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(url);
      toast("Official notice link copied.");
      return;
    }
    const field = document.createElement("textarea");
    field.value = url;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("Clipboard access is unavailable.");
    toast("Official notice link copied.");
  } catch {
    toast("Could not copy the link. Open the official notice to copy it manually.");
  }
}

function renderFeed() {
  const localResults = state.serverPaginated ? state.notices : locallyFilteredNotices();
  const total = state.serverPaginated ? state.total : localResults.length;
  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));
  const page = Math.min(state.page, pageCount);
  if (page !== state.page) state.page = page;
  const start = total ? (state.page - 1) * state.pageSize : 0;
  const visible = state.serverPaginated
    ? localResults
    : localResults.slice(start, start + state.pageSize);
  const end = total ? Math.min(start + visible.length, total) : 0;
  const hasFilters = Boolean(state.query || state.semester !== "all" || state.category !== "all");

  dom.reset.hidden = !hasFilters;
  dom.empty.hidden = visible.length > 0 || state.loading;
  const loadFailed = state.source === "unavailable" && !state.notices.length;
  dom.emptyTitle.textContent = loadFailed ? "Notices could not be loaded" : "No matching notices";
  dom.emptyText.textContent = loadFailed
    ? "The official source could not be reached. Check your connection and try again."
    : "Try a different search or remove one of your filters.";
  dom.emptyReset.textContent = loadFailed ? "Try again" : "Clear all filters";
  dom.emptyReset.hidden = !loadFailed && !hasFilters;
  dom.feed.hidden = visible.length === 0 && !state.loading;
  dom.pagination.hidden = total <= state.pageSize;
  dom.pagePrevious.disabled = state.page <= 1 || state.loading;
  dom.pageNext.disabled = state.page >= pageCount || state.loading;
  dom.pageStatus.textContent = `Page ${state.page} of ${pageCount}`;

  if (!state.notices.length && state.loading) {
    dom.feed.replaceChildren(...Array.from({ length: 3 }, () => {
      const skeleton = document.createElement("article");
      skeleton.className = "notice-card is-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      return skeleton;
    }));
    dom.resultLine.textContent = "Loading notices…";
    return;
  }

  if (!visible.length) {
    dom.feed.replaceChildren();
    dom.resultLine.textContent = loadFailed
      ? "The notice source is unavailable."
      : "No notices match these filters.";
    return;
  }

  const kind = state.source === "live" && !hasFilters ? "recent notices" : "notices";
  dom.resultLine.textContent = hasFilters
    ? `Showing ${start + 1}–${end} of ${total} matching ${kind}`
    : `Showing ${start + 1}–${end} of ${total} ${kind}`;
  dom.feed.replaceChildren(...visible.map(noticeCard));
}

function render() {
  renderStats();
  renderCategories();
  renderStatus();
  renderBanner();
  renderFeed();
}

function changeFilters() {
  state.page = 1;
  render();
  fetchFeed({ silent: true });
}

function resetFilters() {
  state.query = "";
  state.category = "all";
  state.semester = "all";
  state.sort = "newest";
  state.page = 1;
  dom.search.value = "";
  dom.semester.value = "all";
  dom.sort.value = "newest";
  render();
  fetchFeed({ silent: true });
}

let documentPreviewTimer = null;
function showDocument(button) {
  const url = button.dataset.previewUrl;
  if (!url || (!url.startsWith("/api/document?") && !isOfficialUrl(url))) {
    toast("This document link is not available.");
    return;
  }
  const filename = button.dataset.filename || "Notice PDF";
  const downloadUrl = button.dataset.downloadUrl || url;
  dom.documentTitle.textContent = filename;
  dom.documentStatus.hidden = false;
  dom.documentStatus.textContent = "Loading document preview…";
  dom.documentFrame.hidden = true;
  dom.documentFrame.src = "about:blank";
  dom.documentDownload.href = downloadUrl;
  dom.documentDownload.download = filename;
  dom.documentOriginal.href = button.dataset.noticeUrl || "https://iost.tu.edu.np/notices";
  dom.documentOpen.href = url;
  dom.documentFrame.onload = () => {
    if (dom.documentFrame.src.endsWith("about:blank")) return;
    window.clearTimeout(documentPreviewTimer);
    dom.documentStatus.hidden = false;
    dom.documentStatus.textContent = "Preview opened. If it is blank, download the file or open it in a new tab.";
    dom.documentFrame.hidden = false;
  };
  dom.documentFrame.onerror = () => {
    window.clearTimeout(documentPreviewTimer);
    dom.documentStatus.textContent = "The PDF preview could not be loaded. Try downloading it or opening the file in a new tab.";
  };
  if (!dom.dialog.open) dom.dialog.showModal();
  const loadFrame = () => {
    if (!dom.dialog.open) return;
    dom.documentFrame.src = url;
    documentPreviewTimer = window.setTimeout(() => {
      if (dom.documentFrame.hidden) {
        dom.documentStatus.textContent = "The preview is taking too long. Download the file or open it in a new tab.";
      }
    }, 15_000);
  };
  if (url.startsWith("/api/document?")) {
    fetch(url, { headers: { Range: "bytes=0-4" } })
      .then(async (response) => {
        const contentType = response.headers.get("Content-Type") || "";
        const signature = new TextDecoder().decode(await response.arrayBuffer());
        if (!response.ok || !contentType.toLowerCase().includes("application/pdf") ||
            !signature.startsWith("%PDF-")) {
          throw new Error("The archived PDF is unavailable.");
        }
      })
      .then(() => {
        loadFrame();
      })
      .catch(() => {
        if (dom.dialog.open) {
          dom.documentStatus.textContent = "The archived PDF could not be loaded. Try downloading it or opening the file in a new tab.";
        }
      });
  } else {
    loadFrame();
  }
}

function closeMobileNav() {
  dom.nav.classList.remove("is-open");
  dom.menuToggle.setAttribute("aria-expanded", "false");
  $(".sr-only", dom.menuToggle).textContent = "Open navigation menu";
}

dom.refresh.addEventListener("click", () => fetchFeed({ force: true }));
dom.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  window.clearTimeout(searchTimer);
  state.query = dom.search.value.trim().slice(0, 120);
  changeFilters();
});

let searchTimer = null;
dom.search.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.query = dom.search.value.trim().slice(0, 120);
    changeFilters();
  }, 220);
});
dom.semester.addEventListener("change", () => {
  state.semester = dom.semester.value;
  changeFilters();
});
dom.sort.addEventListener("change", () => {
  state.sort = dom.sort.value;
  changeFilters();
});
dom.pageSize.addEventListener("change", () => {
  const value = Number(dom.pageSize.value);
  state.pageSize = PAGE_SIZES.has(value) ? value : 24;
  changeFilters();
});
dom.chips.addEventListener("click", (event) => {
  const chip = event.target.closest(".category-chip");
  if (!chip || !dom.chips.contains(chip)) return;
  state.category = chip.dataset.category;
  changeFilters();
});
dom.pagePrevious.addEventListener("click", () => {
  if (state.page <= 1) return;
  state.page -= 1;
  if (state.serverPaginated) fetchFeed({ silent: true });
  else renderFeed();
});
dom.pageNext.addEventListener("click", () => {
  const count = Math.ceil(state.total / state.pageSize);
  if (state.page >= count) return;
  state.page += 1;
  if (state.serverPaginated) fetchFeed({ silent: true });
  else renderFeed();
});
dom.reset.addEventListener("click", resetFilters);
dom.emptyReset.addEventListener("click", () => {
  if (state.source === "unavailable" && !state.notices.length) fetchFeed({ force: true });
  else resetFilters();
});
dom.feed.addEventListener("click", (event) => {
  const preview = event.target.closest("[data-preview-url]");
  if (preview) showDocument(preview);
});
dom.documentClose.addEventListener("click", () => dom.dialog.close());
dom.dialog.addEventListener("close", () => {
  window.clearTimeout(documentPreviewTimer);
  dom.documentFrame.src = "about:blank";
  dom.documentFrame.hidden = true;
});
dom.dialog.addEventListener("click", (event) => {
  if (event.target === dom.dialog) dom.dialog.close();
});
dom.menuToggle.addEventListener("click", () => {
  const expanded = dom.menuToggle.getAttribute("aria-expanded") === "true";
  dom.menuToggle.setAttribute("aria-expanded", String(!expanded));
  dom.nav.classList.toggle("is-open", !expanded);
  $(".sr-only", dom.menuToggle).textContent = expanded ? "Open navigation menu" : "Close navigation menu";
});
dom.nav.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeMobileNav();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    dom.search.focus();
  }
  if (event.key === "Escape" && document.activeElement === dom.search && dom.search.value) {
    dom.search.value = "";
    state.query = "";
    changeFilters();
  }
});
window.addEventListener("online", () => fetchFeed({ silent: true }));

function boot() {
  render();
  const cached = readCache();
  if (cached) {
    state.notices = cached.notices;
    state.source = cached.source || "unavailable";
    state.site = cached.source_site || "";
    state.fetchedAt = cached.fetched_at || null;
    state.syncStatus = cached.sync_status || null;
    state.total = Number.isSafeInteger(cached.total) ? cached.total : cached.notices.length;
    state.summary = normalizeSummary(cached.summary, cached.notices, cached.source);
    state.serverPaginated = cached.source === "archive";
    render();
  }
  fetchFeed({ silent: true });
}

boot();

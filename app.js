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
  empty: $("#empty"),
  emptyReset: $("#empty-reset"),
  toast: $("#toast"),
  statTotal: $("#stat-total"),
  statExam: $("#stat-exam"),
  statResults: $("#stat-results"),
  statForms: $("#stat-forms"),
};

const CACHE_KEY = "tu-notice-hub:v1";
const CACHE_TTL = 10 * 60 * 1000;
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
};

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

/* IoST publishes on iost.tu.edu.np. The server function may run outside the
   network that reaches that host, so when it can only read the older
   tuiost.edu.np listing, the browser tries the current site itself. The
   visitor is usually in Nepal, where it answers. Any failure is silent and
   the server feed stays as it is. */
const PORTAL_CATEGORIES = [
  ["Exam Routine", ["routine", "schedule", "exam center", "examination center", "time table", "timetable", "तालिका"]],
  ["Results", ["result", "re-total", "retotaling", "re-totaling", "topper", "pass list", "नतिजा", "नतीजा", "फलाफल"]],
  ["Form Fill Up", ["form fill", "fill-up", "fill up", "registration", "deadline", "apply", "फाराम भर्ने", "फारम भर्ने", "आवेदन फाराम"]],
];

const PORTAL_SEMESTERS = [
  ["8th Sem", [/\b8th\s+sem/i, /\beighth\s+sem/i, /\bviii\s+sem/i]],
  ["7th Sem", [/\b7th\s+sem/i, /\bseventh\s+sem/i, /\bvii\s+sem/i]],
  ["6th Sem", [/\b6th\s+sem/i, /\bsixth\s+sem/i, /\bvi\s+sem/i]],
  ["5th Sem", [/\b5th\s+sem/i, /\bfifth\s+sem/i, /\bv\s+sem/i]],
  ["4th Sem", [/\b4th\s+sem/i, /\bfourth\s+sem/i, /\biv\s+sem/i]],
  ["3rd Sem", [/\b3rd\s+sem/i, /\bthird\s+sem/i, /\biii\s+sem/i]],
  ["2nd Sem", [/\b2nd\s+sem/i, /\bsecond\s+sem/i, /\bii\s+sem/i]],
  ["1st Sem", [/\b1st\s+sem/i, /\bfirst\s+sem/i, /\bi\s+sem/i]],
];

function classifyPortal(title) {
  const lower = title.toLowerCase();
  let category = "General Notice";
  for (const [name, words] of PORTAL_CATEGORIES) {
    if (words.some((word) => lower.includes(word))) {
      category = name;
      break;
    }
  }
  let semester = "All Semesters";
  for (const [name, patterns] of PORTAL_SEMESTERS) {
    if (patterns.some((pattern) => pattern.test(lower))) {
      semester = name;
      break;
    }
  }
  const urgent =
    category === "Exam Routine" ||
    category === "Form Fill Up" ||
    lower.includes("last date");
  return { category, semester, urgent };
}

function digest12(value) {
  let h = 5381;
  for (let i = 0; i < value.length; i++) h = ((h << 5) + h) ^ value.charCodeAt(i);
  return (h >>> 0).toString(36).padStart(7, "0");
}

function readCurrentPortal(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const notices = [];
  const seen = new Set();
  for (const block of doc.querySelectorAll("div.recent-post-wrapper")) {
    const link = block.querySelector("div.detail a[href]");
    if (!link) continue;
    const heading = link.querySelector("h5");
    const title = String((heading && heading.textContent) || link.textContent || "")
      .replace(/\s+/g, " ")
      .trim();
    if (title.length < 8) continue;
    let url;
    try {
      url = new URL(link.getAttribute("href"), "https://iost.tu.edu.np/").href;
    } catch {
      continue;
    }
    if (seen.has(url)) continue;
    seen.add(url);
    const dateEl = block.querySelector(".nep_date") || block.querySelector(".date");
    const raw = dateEl ? dateEl.textContent.trim() : "";
    const published = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null;
    notices.push({
      id: digest12(`${title}|${url}`),
      title: title.replace(/\s*[\u2014\u2013]\s*/g, " - ").slice(0, 180),
      url,
      publish_date: published,
      date_label: raw || "Undated",
      is_pdf: /\.pdf($|\?)/i.test(url),
      source: "live",
      ...classifyPortal(title),
    });
  }
  notices.sort(
    (a, b) =>
      String(b.publish_date || "").localeCompare(String(a.publish_date || "")) ||
      b.title.localeCompare(a.title)
  );
  return notices;
}

async function portalFetch(url) {
  // An unreachable host can hang for a minute. The feed must never wait that
  // long for a site that may simply not answer this network.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);
  try {
    return await fetch(url, { credentials: "omit", signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function readPortalDirectly() {
  try {
    const notices = [];
    const seen = new Set();
    let url = "https://iost.tu.edu.np/notices";
    // Two cursor pages is enough for a feed that shows twenty cards.
    for (let page = 0; page < 2 && url; page += 1) {
      const response = await portalFetch(url);
      if (!response.ok) break;
      const html = await response.text();
      const batch = readCurrentPortal(html).filter((notice) => !seen.has(notice.url));
      batch.forEach((notice) => seen.add(notice.url));
      notices.push(...batch);
      if (!batch.length) break;
      const doc = new DOMParser().parseFromString(html, "text/html");
      const next = [...doc.querySelectorAll("ul.pagination a.page-link[href]")].find((link) =>
        link.href.includes("cursor=") && !/previous/i.test(link.textContent)
      );
      url = next ? new URL(next.getAttribute("href"), "https://iost.tu.edu.np/notices").href : "";
    }
    if (!notices.length) return null;
    notices.sort(
      (a, b) =>
        String(b.publish_date || "").localeCompare(String(a.publish_date || "")) ||
        b.title.localeCompare(a.title)
    );
    return notices;
  } catch {
    // Blocked by CORS, offline, or the host does not answer from here.
    return null;
  }
}

async function fetchFeed({ force = false, silent = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  dom.refresh.classList.add("is-busy");
  dom.refresh.disabled = true;
  if (!state.notices.length) dom.feed.setAttribute("aria-busy", "true");

  try {
    /* Read iost.tu.edu.np from the visitor's own network first. The serverless
       function runs outside it, and a cached older listing is worse than a
       short one from the site that is actually publishing. */
    const direct = await readPortalDirectly();
    if (direct && direct.length) {
      const known = new Set(state.notices.map((notice) => notice.id));
      const fresh = state.notices.length ? direct.filter((notice) => !known.has(notice.id)) : [];
      state.notices = direct;
      state.source = "live";
      state.site = "iost.tu.edu.np";
      state.fetchedAt = new Date().toISOString();
      state.error = null;
      state.stale = false;
      writeCache({
        notices: state.notices,
        source: state.source,
        site: state.site,
        fetched_at: state.fetchedAt,
        error: null,
      });
      render();
      if (fresh.length && !silent) {
        toast(`${fresh.length} new notice${fresh.length === 1 ? "" : "s"} published on iost.tu.edu.np`);
      } else if (force) {
        toast("Checked iost.tu.edu.np just now");
      }
      return;
    }

    const url = `/api/notices?t=${Date.now()}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const incoming = Array.isArray(payload.notices) ? payload.notices : [];
    const hadLive = state.source === "live" && state.notices.length > 0;
    const known = new Set(state.notices.map((notice) => notice.id));
    const fresh = state.notices.length ? incoming.filter((notice) => !known.has(notice.id)) : [];

    // A failed scrape should never replace a good live feed with six curated cards.
    if (payload.source !== "live" && hadLive) {
      state.stale = true;
      state.error = payload.error || "The TU portal did not respond.";
      renderBadge();
      renderBanner();
      if (force) toast("Portal unreachable, keeping the last live feed");
      return;
    }

    state.notices = incoming;
    state.source = payload.source === "live" ? "live" : "fallback";
    state.site = payload.source_site || "";
    state.fetchedAt = payload.fetched_at || new Date().toISOString();
    state.error = payload.error || null;
    state.stale = false;
    writeCache({ notices: state.notices, source: state.source, site: state.site, fetched_at: state.fetchedAt, error: state.error });
    render();
    if (fresh.length && !silent) {
      toast(`${fresh.length} new notice${fresh.length === 1 ? "" : "s"} published on ${state.site || "the portal"}`);
    } else if (force) {
      toast(state.source === "live" ? `Checked ${state.site || "the portal"} just now` : "Portal unreachable, fallback refreshed");
    }
  } catch (error) {
    state.error = String(error.message || error);
    if (!state.notices.length) {
      const cached = readCache();
      if (cached) {
        state.notices = cached.notices;
        state.source = cached.source || "fallback";
        state.site = cached.site || "";
        state.fetchedAt = cached.fetched_at || null;
      }
    }
    state.source = state.notices.length ? state.source : "error";
    render();
    if (force) toast("Could not reach the feed, showing cached notices");
  } finally {
    state.loading = false;
    dom.refresh.classList.remove("is-busy");
    dom.refresh.disabled = false;
    dom.feed.setAttribute("aria-busy", "false");
    renderBadge();
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
  dom.statTotal.textContent = String(state.notices.length);
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
    live: ["Live", "live"],
    fallback: ["Fallback", "fallback"],
    error: ["Offline", "error"],
    loading: ["Checking", "loading"],
  };
  const [label, kind] = map[state.source] || map.loading;
  dom.sourceText.textContent = label;
  dom.sourceBadge.dataset.source = kind;
  // IoST publishes on iost.tu.edu.np. tuiost.edu.np still answers but has not
  // taken a notice since 2023, so say so instead of showing a quiet "Live".
  const site = state.site || "";
  const staleSite = site === "tuiost.edu.np";
  if (state.source === "live") {
    if (staleSite) {
      dom.sourceText.textContent = "Old portal";
      dom.sourceBadge.dataset.source = "fallback";
      dom.sourceBadge.title =
        "iost.tu.edu.np could not be reached, so this is the older tuiost.edu.np feed, which stopped publishing in 2023.";
    } else {
      dom.sourceBadge.title = site ? `Reading ${site}` : "Reading the IoST portal";
    }
  }
  dom.sync.textContent = state.loading ? "Syncing…" : formatSync(state.fetchedAt);
}

function renderBanner() {
  if (state.stale) {
    dom.banner.hidden = false;
    dom.bannerText.textContent =
      "The latest refresh failed, so this is the last live feed. Try Refresh again in a minute.";
  } else if (state.source === "live" && state.site === "tuiost.edu.np") {
    dom.banner.hidden = false;
    dom.bannerText.textContent =
      "iost.tu.edu.np was not reachable from this server, so the older tuiost.edu.np feed is shown. It stopped publishing in 2023.";
  } else if (state.source === "fallback" || state.source === "error") {
    dom.banner.hidden = false;
    dom.bannerText.textContent = state.error
      ? `Showing the curated fallback list. ${state.error}`
      : "Showing the curated fallback list while the TU portal is unavailable.";
  } else {
    dom.banner.hidden = true;
    dom.bannerText.textContent = "";
  }
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
  const link = document.createElement("a");
  link.href = notice.url;
  link.target = "_blank";
  link.rel = "noreferrer noopener";
  link.textContent = notice.title;
  title.append(link);

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

  const open = document.createElement("a");
  open.className = "icon-btn";
  open.href = notice.url;
  open.target = "_blank";
  open.rel = "noreferrer noopener";
  open.setAttribute("aria-label", notice.is_pdf ? "Open notice PDF" : "Open notice");
  open.title = notice.is_pdf ? "Open PDF" : "Open notice";
  open.innerHTML = notice.is_pdf
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13h4M10 16h4"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';

  actions.append(copy, open);
  foot.append(dateWrap, actions);
  article.append(tags, title, foot);
  return article;
}

function renderFeed() {
  const list = filtered();
  const hasFilters = Boolean(state.query.trim()) || state.semester !== "all" || state.category !== "all";

  dom.reset.hidden = !hasFilters;
  dom.empty.hidden = list.length > 0 || state.loading;
  dom.feed.hidden = list.length === 0;

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

  dom.resultLine.textContent = hasFilters
    ? `Showing ${list.length} of ${state.notices.length} notices`
    : `${state.notices.length} notices · newest first`;

  dom.feed.replaceChildren(...list.map(noticeCard));
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
    renderFeed();
    dom.resultLine.parentElement.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, 120);
});

dom.semester.addEventListener("change", (event) => {
  state.semester = event.target.value;
  renderFeed();
});

dom.chips.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  state.category = chip.dataset.category;
  renderChips();
  renderFeed();
});

function resetFilters() {
  state.query = "";
  state.semester = "all";
  state.category = "all";
  dom.search.value = "";
  dom.semester.value = "all";
  render();
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
    renderFeed();
    dom.search.blur();
  }
});

window.addEventListener("online", () => fetchFeed({ silent: true }));

// The feed follows the portal by itself: every five minutes, and again whenever
// the tab comes back into focus, so a new notice shows up without a reload.
const POLL_MS = 5 * 60 * 1000;
window.setInterval(() => {
  if (document.visibilityState === "visible") fetchFeed({ silent: true });
}, POLL_MS);

function refreshIfStale() {
  if (document.visibilityState !== "visible") return;
  const age = state.fetchedAt ? Date.now() - new Date(state.fetchedAt).getTime() : Infinity;
  if (age > 60_000) fetchFeed({ silent: true });
}

document.addEventListener("visibilitychange", refreshIfStale);
window.addEventListener("focus", refreshIfStale);

/* ------------------------------------------------------------------ boot */

function boot() {
  render();
  const cached = readCache();
  if (cached) {
    state.notices = cached.notices;
    state.source = cached.source || "fallback";
    state.site = cached.site || "";
    state.fetchedAt = cached.fetched_at || null;
    state.error = cached.error || null;
    render();
    const age = state.fetchedAt ? Date.now() - new Date(state.fetchedAt).getTime() : Infinity;
    // The curated fallback is a stopgap, never a reason to skip a live check.
    if (age > CACHE_TTL || state.source !== "live") fetchFeed();
  } else {
    fetchFeed();
  }

  window.setInterval(renderBadge, 30_000);
}

boot();

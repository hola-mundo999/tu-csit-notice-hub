"""Vercel serverless function: live TU IOST notices.

GET /api/notices
  -> { notices: [...], source: "live" | "fallback", fetched_at, portal, error }

The TU portal renders each notice as:

    <div class="mt-3">
      <a href="https://tuiost.edu.np/storage/notice/<file>.pdf"><b>Title</b></a>
      <small class="text-muted">26th Jul, 2023</small>
    </div>

The original dashboard looked for `.notice-list-item, .table tbody tr,
.list-group-item`, which no longer exist, so every scrape silently produced
nothing and the UI always showed the curated list. This parses the real markup,
classifies each notice, and falls back to a bundled set when the portal is
unreachable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTAL = "https://tuiost.edu.np/notices"
BASE = "https://tuiost.edu.np"
# IoST moved its own site in 2081. tuiost.edu.np still answers but stopped
# publishing, so its newest entry sits three years in the past. iost.tu.edu.np
# carries the current notices, though some networks outside Nepal cannot reach
# it, which is why the legacy portal stays as the second source.
IOST = "https://iost.tu.edu.np"
IOST_NOTICES = f"{IOST}/notices"
IOST_TIMEOUT = 10
IOST_PAGES = 3
TIMEOUT = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# A semester is only claimed when the number is attached to "sem" / "semester";
# matching a bare "Second" turned a Ph.D. festival announcement into 2nd Sem.
SEMESTERS = [
    ("8th Sem", [r"\b8th\s+sem", r"\beighth\s+sem", r"\bviii\s+sem"]),
    ("7th Sem", [r"\b7th\s+sem", r"\bseventh\s+sem", r"\bvii\s+sem"]),
    ("6th Sem", [r"\b6th\s+sem", r"\bsixth\s+sem", r"\bvi\s+sem"]),
    ("5th Sem", [r"\b5th\s+sem", r"\bfifth\s+sem", r"\bv\s+sem"]),
    ("4th Sem", [r"\b4th\s+sem", r"\bfourth\s+sem", r"\biv\s+sem"]),
    ("3rd Sem", [r"\b3rd\s+sem", r"\bthird\s+sem", r"\biii\s+sem"]),
    ("2nd Sem", [r"\b2nd\s+sem", r"\bsecond\s+sem", r"\bii\s+sem"]),
    ("1st Sem", [r"\b1st\s+sem", r"\bfirst\s+sem", r"\bi\s+sem"]),
]

CATEGORY_RULES = [
    ("Exam Routine", ("routine", "schedule", "exam center", "examination center", "time table", "timetable", "तालिका")),
    ("Results", ("result", "re-total", "retotaling", "re-totaling", "topper", "pass list", "नतिजा", "नतीजा", "फलाफल")),
    ("Form Fill Up", ("form fill", "fill-up", "fill up", "registration", "deadline", "apply", "फाराम भर्ने", "फारम भर्ने", "आवेदन फाराम")),
]

CURATED = [
    {
        "title": "B.Sc. CSIT 4th Semester Regular & Back Exam Routine Published",
        "category": "Exam Routine",
        "semester": "4th Sem",
        "publish_date": "2081-06-24",
        "url": f"{BASE}/notices",
        "urgent": True,
    },
    {
        "title": "B.Sc. CSIT 6th Semester Final Examination Results Published",
        "category": "Results",
        "semester": "6th Sem",
        "publish_date": "2081-06-18",
        "url": f"{BASE}/notices",
        "urgent": True,
    },
    {
        "title": "Examination Form Fill-up Notice for B.Sc. CSIT 2nd Semester Regular Candidates",
        "category": "Form Fill Up",
        "semester": "2nd Sem",
        "publish_date": "2081-06-10",
        "url": f"{BASE}/notices",
        "urgent": False,
    },
    {
        "title": "B.Sc. CSIT 8th Semester Internship & Project II Defense Schedule",
        "category": "General Notice",
        "semester": "8th Sem",
        "publish_date": "2081-05-29",
        "url": f"{BASE}/notices",
        "urgent": False,
    },
    {
        "title": "B.Sc. CSIT 1st Semester Examination Center Allocation Notice",
        "category": "Exam Routine",
        "semester": "1st Sem",
        "publish_date": "2081-05-15",
        "url": f"{BASE}/notices",
        "urgent": True,
    },
    {
        "title": "Notice Regarding Re-totaling Results for B.Sc. CSIT 3rd & 5th Semester",
        "category": "Results",
        "semester": "3rd Sem",
        "publish_date": "2081-05-02",
        "url": f"{BASE}/notices",
        "urgent": False,
    },
]

DATE_FORMATS = ("%d %b, %Y", "%d %B, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y")


def parse_date(raw: str) -> Optional[str]:
    text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", (raw or "").strip())
    text = re.sub(r"\s+", " ", text)
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def classify(title: str) -> Dict[str, Any]:
    lower = title.lower()
    category = "General Notice"
    for name, keywords in CATEGORY_RULES:
        if any(word in lower for word in keywords):
            category = name
            break

    semester = "All Semesters"
    for name, patterns in SEMESTERS:
        if any(re.search(pattern, lower) for pattern in patterns):
            semester = name
            break

    urgent = category in ("Exam Routine", "Form Fill Up") or "urgent" in lower or "last date" in lower
    return {"category": category, "semester": semester, "urgent": urgent}


def normalize_dashes(text: str) -> str:
    """The portal mixes en and em dashes into titles; house style uses a hyphen."""
    text = re.sub(r"\s*[\u2014\u2013]\s*", " - ", text or "")
    text = re.sub(r"[\u2010\u2011\u2012\u2015\u2212]", "-", text)
    return text


def build_notice(title: str, url: str, published: Optional[str], raw_date: str, source: str) -> Dict[str, Any]:
    clean = re.sub(r"\s+", " ", normalize_dashes(title)).strip(" .-")
    meta = classify(clean)
    digest = hashlib.md5(f"{clean}|{url}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": digest,
        "title": clean[:180],
        "url": url,
        "publish_date": published,
        "date_label": raw_date.strip() if raw_date else "Undated",
        "category": meta["category"],
        "semester": meta["semester"],
        "urgent": meta["urgent"],
        "is_pdf": url.lower().endswith(".pdf"),
        "source": source,
    }


def parse_iost_page(soup: BeautifulSoup, seen: set) -> List[Dict[str, Any]]:
    """Parse the current IoST site, whose list is one block per notice.

        <div class="recent-post-wrapper shdow">
          <div class="date"><span class="nep_date">2026-07-06</span></div>
          <div class="detail"><a href="/notices/13684"><h5>Title</h5></a></div>
        </div>

    The link is a notice page rather than a PDF, and pagination is a cursor in
    the query string rather than a page number.
    """
    notices: List[Dict[str, Any]] = []
    for block in soup.select("div.recent-post-wrapper"):
        link = block.select_one("div.detail a[href]")
        if not link:
            continue
        heading = link.find("h5")
        title = (heading.get_text(" ", strip=True) if heading else "") or link.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        date_el = block.select_one(".nep_date") or block.select_one(".date")
        raw_date = date_el.get_text(" ", strip=True) if date_el else ""
        notice = build_notice(title, urljoin(IOST + "/", link["href"]), parse_date(raw_date), raw_date, "live")
        if notice["url"] in seen:
            continue
        seen.add(notice["url"])
        notices.append(notice)
    return notices


def scrape_iost() -> List[Dict[str, Any]]:
    """Current IoST notices, followed through the cursor pagination."""
    notices: List[Dict[str, Any]] = []
    seen: set = set()
    url: Optional[str] = IOST_NOTICES
    for _ in range(IOST_PAGES):
        if not url:
            break
        response = requests.get(url, headers=HEADERS, timeout=IOST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        found = parse_iost_page(soup, seen)
        notices.extend(found)
        if len(found) < 1:
            break
        next_link = None
        for item in soup.select("ul.pagination a.page-link[href]"):
            href = item.get("href", "")
            if "cursor=" in href and "Previous" not in item.get_text():
                next_link = href
                break
        url = urljoin(IOST_NOTICES, next_link) if next_link else None
    notices.sort(key=lambda item: (item["publish_date"] or "", item["title"]), reverse=True)
    return notices


def scrape_legacy() -> List[Dict[str, Any]]:
    """The old tuiost.edu.np portal, kept for networks that cannot reach IoST."""
    response = requests.get(PORTAL, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    notices: List[Dict[str, Any]] = []
    seen = set()

    # Real markup: div.mt-3 blocks inside the notice list.
    for block in soup.select("div.feature-content div.mt-3"):
        link = block.find("a", href=True)
        if not link:
            continue
        href = urljoin(BASE, link["href"])
        title_el = link.find("b") or link
        title = title_el.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        date_el = block.find("small")
        raw_date = date_el.get_text(" ", strip=True) if date_el else ""
        notice = build_notice(title, href, parse_date(raw_date), raw_date, "live")
        if notice["url"] in seen:
            continue
        seen.add(notice["url"])
        notices.append(notice)

    # Fallback selector for older / alternative layouts.
    if not notices:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/storage/notice/" not in href and "/notice/" not in href:
                continue
            title = link.get_text(" ", strip=True)
            if len(title) < 12:
                continue
            block = link.find_parent(["div", "li", "tr"]) or link
            raw_date = ""
            date_el = block.find("small") if hasattr(block, "find") else None
            if date_el:
                raw_date = date_el.get_text(" ", strip=True)
            notice = build_notice(title, urljoin(BASE, href), parse_date(raw_date), raw_date, "live")
            if notice["url"] in seen:
                continue
            seen.add(notice["url"])
            notices.append(notice)

    notices.sort(key=lambda item: (item["publish_date"] or "", item["title"]), reverse=True)
    return notices


def scrape() -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """Read the freshest portal this network can reach.

    Returns (notices, site label, error). The new site first, because it is
    the only one still publishing; the legacy portal second, so the feed still
    works from a network where iost.tu.edu.np does not answer.
    """
    errors: List[str] = []
    for label, reader in (("iost.tu.edu.np", scrape_iost), ("tuiost.edu.np", scrape_legacy)):
        try:
            notices = reader()
        except Exception as exc:  # noqa: BLE001 - try the next portal
            errors.append(f"{label}: {type(exc).__name__}"[:80])
            continue
        if notices:
            return notices, label, None
        errors.append(f"{label}: no recognisable notices")
    return [], "none", "; ".join(errors)[:200]


def fallback_notices(error: Optional[str]) -> List[Dict[str, Any]]:
    today = dt.date.today().isoformat()
    return [
        {
            **build_notice(item["title"], item["url"], item["publish_date"], item["publish_date"], "fallback"),
            "urgent": item["urgent"],
            "category": item["category"],
            "semester": item["semester"],
        }
        for item in CURATED
    ] or []


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (Vercel entrypoint)
        error = None
        notices: List[Dict[str, Any]] = []
        source = "live"
        site = ""

        notices, site, error = scrape()

        if not notices:
            source = "fallback"
            site = "curated list"
            notices = fallback_notices(error)

        payload = {
            "notices": notices,
            "source": source,
            "source_site": site,
            "portal": IOST_NOTICES,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "error": error,
        }

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The feed must mirror the portal, so never let a CDN or browser serve a
        # minutes old copy. The client polls on its own schedule.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

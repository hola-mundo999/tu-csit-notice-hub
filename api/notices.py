"""Read archived notices or return a bounded live preview from official IoST."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import database

IOST = "https://iost.tu.edu.np"
IOST_NOTICES = f"{IOST}/notices"
IOST_TIMEOUT = 8
IOST_PAGES = 3
MAX_RETRIES = 2
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

DATE_FORMATS = ("%d %b, %Y", "%d %B, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y")


def _official_notice_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "iost.tu.edu.np"
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
        and parsed.path.startswith("/notices/")
    )


def _get(url: str) -> requests.Response:
    current_url = url
    if not _safe_listing_url(current_url):
        raise ValueError("Rejected URL outside the official IoST notice site.")
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            for _ in range(5):
                response = requests.get(
                    current_url,
                    headers=HEADERS,
                    timeout=IOST_TIMEOUT,
                    allow_redirects=False,
                )
                if response.is_redirect:
                    location = response.headers.get("Location")
                    response.close()
                    if not location:
                        raise ValueError("Official IoST returned a redirect without a location.")
                    current_url = urljoin(current_url, location)
                    if not _safe_listing_url(current_url):
                        raise ValueError("Rejected redirect outside the official IoST notice site.")
                    continue
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    response.close()
                    raise
                return response
            raise ValueError("Too many redirects from the official IoST site.")
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
    if last_error is None:
        raise RuntimeError("Source request failed without an error")
    raise last_error


def _safe_listing_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "iost.tu.edu.np"
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
        and (parsed.path == "/notices" or parsed.path.startswith("/notices/"))
    )


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

    urgent = category in ("Exam Routine", "Results") or "urgent" in lower or "last date" in lower
    return {"category": category, "semester": semester, "urgent": urgent}


def normalize_dashes(text: str) -> str:
    """The portal mixes en and em dashes into titles; house style uses a hyphen."""
    text = re.sub(r"\s*[\u2014\u2013]\s*", " - ", text or "")
    text = re.sub(r"[\u2010\u2011\u2012\u2015\u2212]", "-", text)
    return text


def build_notice(title: str, url: str, published: Optional[str], raw_date: str, source: str) -> Dict[str, Any]:
    clean = re.sub(r"\s+", " ", normalize_dashes(title)).strip(" .-")
    meta = classify(clean)
    source_id_match = re.search(r"/notices/(\d+)/?$", urlparse(url).path)
    source_id = source_id_match.group(1) if source_id_match else None
    digest = hashlib.sha256(f"{clean}|{url}".encode("utf-8")).hexdigest()
    return {
        "id": digest,
        "source_id": source_id,
        "title": clean[:180],
        "url": url,
        "source_url": url,
        "publish_date": published,
        "source_published_at": published,
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
        notice_url = urljoin(IOST + "/", link["href"])
        if not _official_notice_url(notice_url):
            continue
        notice = build_notice(title, notice_url, parse_date(raw_date), raw_date, "live")
        if notice["url"] in seen:
            continue
        seen.add(notice["url"])
        notices.append(notice)
    return notices


def parse_iost_detail(soup: BeautifulSoup, source_url: str) -> Dict[str, Any]:
    title_element = soup.select_one(".detail-page-inner h4.title")
    if title_element is None:
        raise ValueError(f"Official notice page has no title: {source_url}")
    title = title_element.get_text(" ", strip=True)
    date_element = soup.select_one(".detail-page-inner .nep_date")
    raw_date = date_element.get_text(" ", strip=True) if date_element else ""
    attachments: List[Dict[str, Any]] = []
    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if not link:
            continue
        attachment_url = urljoin(source_url, link["href"])
        try:
            parsed = urlparse(attachment_url)
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"portal.tu.edu.np", "iost.tu.edu.np"}
            or port not in (None, 443)
            or parsed.username
            or parsed.password
        ):
            continue
        filename = parsed.path.rsplit("/", 1)[-1]
        if not filename or "." not in filename:
            filename = cells[0].get_text(" ", strip=True) if cells else ""
        file_type = cells[1].get_text(" ", strip=True).lower() if len(cells) > 1 else ""
        attachments.append({
            "url": attachment_url,
            "filename": filename,
            "file_type": file_type or parsed.path.rsplit(".", 1)[-1].lower(),
        })
    return {
        "title": title,
        "publish_date": parse_date(raw_date),
        "date_label": raw_date or "Undated",
        "attachments": attachments,
    }


def scrape_iost(max_pages: int = IOST_PAGES) -> List[Dict[str, Any]]:
    """Current IoST notices, followed through the cursor pagination."""
    notices: List[Dict[str, Any]] = []
    seen: set = set()
    url: Optional[str] = IOST_NOTICES
    visited_pages: set = set()
    for _ in range(max_pages):
        if not url:
            break
        if url in visited_pages:
            raise ValueError("IoST pagination cursor repeated")
        visited_pages.add(url)
        response = _get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        found = parse_iost_page(soup, seen)
        notices.extend(found)
        if len(found) < 1:
            break
        next_link = None
        for item in soup.select("ul.pagination a.page-link[href]"):
            href = item.get("href", "")
            if "cursor=" in href and "previous" not in item.get_text().lower():
                candidate = urljoin(IOST_NOTICES, href)
                if urlparse(candidate).hostname == "iost.tu.edu.np":
                    next_link = candidate
                break
        url = next_link
    notices.sort(key=lambda item: (item["publish_date"] or "", item["title"]), reverse=True)
    return notices


def scrape() -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """Read the authoritative IoST notice board; never substitute invented or stale data."""
    try:
        notices = scrape_iost()
    except Exception as exc:
        return [], "iost.tu.edu.np", f"{type(exc).__name__}: {exc}"[:200]
    if not notices:
        return [], "iost.tu.edu.np", "The official listing contained no recognizable notices."
    return notices, "iost.tu.edu.np", None


def archive_notices(
    page: int = 1,
    page_size: int = 24,
    category: Optional[str] = None,
    semester: Optional[str] = None,
    search_query: Optional[str] = None,
) -> Tuple[Optional[List[Dict[str, Any]]], int]:
    if not Path(database.DB_PATH).is_file():
        return None, 0
    database.init_db(database.DB_PATH)
    records, total = database.get_notice_page(
        db_path=database.DB_PATH,
        source_only=True,
        page=page,
        page_size=page_size,
        category=category,
        semester=semester,
        search_query=search_query,
    )
    if not records:
        return [], total
    archived: List[Dict[str, Any]] = []
    for record in records:
        attachments = []
        for item in database.get_attachments(record["id"], database.DB_PATH):
            stored = bool(item.get("stored_file_path") and Path(item["stored_file_path"]).is_file())
            attachments.append({
                "id": item["id"],
                "url": item["source_url"],
                "filename": item["original_filename"],
                "mime_type": item["mime_type"],
                "available": stored,
                "view_url": (
                    f"/api/document?attachment_id={item['id']}&disposition=inline" if stored else None
                ),
                "download_url": (
                    f"/api/document?attachment_id={item['id']}&disposition=attachment" if stored else None
                ),
            })
        archived.append({
            "id": record.get("source_id") or str(record["id"]),
            "source_id": record.get("source_id"),
            "title": record["title"],
            "url": record.get("source_url") or record["url"],
            "publish_date": record.get("source_published_at") or record.get("publish_date"),
            "date_label": record.get("source_published_at") or record.get("publish_date") or "Undated",
            "category": record["category"],
            "semester": record["semester"],
            "urgent": bool(record["is_urgent"]),
            "source": "archive",
            "attachments": attachments,
        })
    return archived, total


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (Vercel entrypoint)
        error = None
        notices: List[Dict[str, Any]] = []
        params = parse_qs(urlparse(self.path).query)
        try:
            page = max(1, int(params.get("page", ["1"])[0]))
            page_size = min(100, max(1, int(params.get("page_size", ["24"])[0])))
        except ValueError:
            self.send_error(400, "page and page_size must be integers.")
            return
        category = params.get("category", [None])[0]
        semester = params.get("semester", [None])[0]
        search_query = params.get("q", [""])[0].strip()[:120]
        archived_notices, total = archive_notices(
            page=page,
            page_size=page_size,
            category=category,
            semester=semester,
            search_query=search_query,
        )
        notices = archived_notices or []
        source = "archive" if notices else "live"
        site = "local archive" if notices else ""
        latest_run = None
        last_success = None
        has_filters = bool(category or semester or search_query)
        if archived_notices is None or (total == 0 and not has_filters):
            notices, site, error = scrape()
            total = len(notices)
            source = "live" if notices else "unavailable"
        else:
            source = "archive"
            latest_run = database.get_latest_sync_run(database.DB_PATH)
            last_success = database.get_latest_sync_run(database.DB_PATH, status="completed")

        payload = {
            "notices": notices,
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": source,
            "source_site": site,
            "portal": IOST_NOTICES,
            "fetched_at": (
                last_success.get("finished_at") if last_success else
                dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") if source != "archive" else None
            ),
            "error": error,
            "sync_status": {
                "last_attempted_at": latest_run.get("started_at") if latest_run else None,
                "last_successful_at": last_success.get("finished_at") if last_success else None,
                "status": latest_run.get("status") if latest_run else "not_configured",
                "failed": latest_run.get("failed", 0) if latest_run else 0,
                "pending_failures": len(database.get_sync_failures(database.DB_PATH)) if source == "archive" else 0,
            },
        }

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, s-maxage=60, stale-while-revalidate=300")
        self.end_headers()
        self.wfile.write(body)

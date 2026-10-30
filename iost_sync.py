"""Incremental and resumable importer for the official IoST notice archive."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import database
from api import notices as iost

DB_PATH = database.DB_PATH
STORAGE_DIR = Path(os.environ.get("NOTICE_STORAGE_DIR", "notice_files")).resolve()
MAX_FILE_BYTES = 25 * 1024 * 1024
REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 1.0
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/octet-stream",
}


class ImportErrorDetail(Exception):
    pass


def _validated_url(url: str, attachment: bool = False) -> str:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ImportErrorDetail("Rejected malformed source URL.") from exc
    allowed_hosts = {"iost.tu.edu.np", "portal.tu.edu.np"} if attachment else {"iost.tu.edu.np"}
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise ImportErrorDetail("Rejected URL outside the official IoST document hosts.")
    if not attachment and not parsed.path.startswith("/notices"):
        raise ImportErrorDetail("Rejected URL outside the official notice listing.")
    return url


def _request(url: str, attachment: bool = False, stream: bool = False) -> requests.Response:
    current_url = _validated_url(url, attachment)
    for attempt in range(3):
        try:
            for _ in range(5):
                response = requests.get(
                    current_url,
                    headers=iost.HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                    stream=stream,
                )
                if response.is_redirect:
                    location = response.headers.get("Location")
                    response.close()
                    if not location:
                        raise ImportErrorDetail("Source returned a redirect without a location.")
                    current_url = _validated_url(urljoin(current_url, location), attachment)
                    continue
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    response.close()
                    raise
                return response
            raise ImportErrorDetail("Too many redirects while requesting a source document.")
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(0.5 * (2 ** attempt))
    raise ImportErrorDetail("Source request failed.")


def _next_page(soup: BeautifulSoup) -> Optional[str]:
    for link in soup.select("ul.pagination a.page-link[href]"):
        href = link.get("href", "")
        if "cursor=" in href and "previous" not in link.get_text(" ", strip=True).lower():
            return _validated_url(urljoin(iost.IOST_NOTICES, href))
    return None


def _attachment_filename(attachment: Dict[str, Any], response: requests.Response) -> str:
    content_disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", content_disposition, re.I)
    if match:
        name = unquote(match.group(1) or match.group(2)).strip()
    else:
        name = PurePosixPath(urlparse(attachment["url"]).path).name
    name = Path(name).name.replace("\x00", "").strip()
    if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ImportErrorDetail("Attachment has an unsupported filename or file type.")
    return name


def _valid_signature(path: Path, extension: str) -> bool:
    with path.open("rb") as file:
        header = file.read(16)
    if extension == ".pdf":
        return header.startswith(b"%PDF-")
    if extension in {".doc", ".xls", ".ppt"}:
        return header.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    if extension in {".docx", ".xlsx", ".pptx"}:
        return header.startswith(b"PK\x03\x04")
    return False


def _download_attachment(attachment: Dict[str, Any], source_id: str) -> Tuple[str, str, str, str]:
    response = _request(attachment["url"], attachment=True, stream=True)
    try:
        mime_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime_type not in ALLOWED_MIME_TYPES:
            raise ImportErrorDetail(f"Rejected attachment MIME type: {mime_type or 'unknown'}.")
        filename = _attachment_filename(attachment, response)
        if mime_type != "application/octet-stream":
            expected = {
                ".pdf": "application/pdf",
                ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xls": "application/vnd.ms-excel",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".ppt": "application/vnd.ms-powerpoint",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }[Path(filename).suffix.lower()]
            if mime_type != expected:
                raise ImportErrorDetail("Attachment extension does not match its MIME type.")

        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(dir=STORAGE_DIR, prefix=".download-", delete=False) as temp:
                temp_path = Path(temp.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ImportErrorDetail("Attachment exceeds the 25 MB size limit.")
                    digest.update(chunk)
                    temp.write(chunk)
            if size == 0 or not _valid_signature(temp_path, Path(filename).suffix.lower()):
                raise ImportErrorDetail("Downloaded attachment is empty or has an invalid file signature.")
            content_hash = digest.hexdigest()
            stored_path = STORAGE_DIR / f"{source_id}-{content_hash[:16]}{Path(filename).suffix.lower()}"
            if stored_path.exists():
                temp_path.unlink()
            else:
                os.replace(temp_path, stored_path)
            return filename, mime_type, content_hash, str(stored_path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    finally:
        response.close()


def _record_failure(source_url: str, reason: str, listing_item: Dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("""
            INSERT INTO sync_failures (source_url, reason, last_attempt_at, attempts, notice_json)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                reason = excluded.reason,
                last_attempt_at = excluded.last_attempt_at,
                attempts = sync_failures.attempts + 1,
                resolved_at = NULL,
                notice_json = excluded.notice_json
        """, (
            source_url,
            reason[:500],
            dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            json.dumps(listing_item, ensure_ascii=False),
        ))


def _import_notice(listing_item: Dict[str, Any], dry_run: bool) -> Tuple[bool, int]:
    source_url = listing_item["url"]
    existing_notice = database.get_notice_by_source_url(source_url, DB_PATH)
    if existing_notice and not database.has_sync_failure(source_url, DB_PATH):
        if not dry_run:
            database.touch_notice(source_url, DB_PATH)
        return False, 0
    response = _request(_validated_url(source_url))
    try:
        detail = iost.parse_iost_detail(BeautifulSoup(response.text, "html.parser"), source_url)
    finally:
        response.close()
    notice = dict(listing_item)
    notice["title"] = detail["title"]
    notice["publish_date"] = detail["publish_date"] or listing_item.get("publish_date") or "Undated"
    notice["source_published_at"] = detail["publish_date"] or listing_item.get("publish_date")
    notice["url"] = source_url
    notice["source_url"] = source_url
    if dry_run:
        return not existing_notice, len(detail["attachments"])

    if existing_notice:
        stored_notice = existing_notice
    else:
        database.save_notice(notice, DB_PATH)
        stored_notice = database.get_notice_by_source_url(source_url, DB_PATH)
    if stored_notice is None:
        raise ImportErrorDetail("Notice insert was not visible after commit.")

    attachment_count = 0
    source_id = str(stored_notice.get("source_id") or stored_notice["id"])
    existing = database.get_attachments(stored_notice["id"], DB_PATH)
    existing_urls = {
        item["source_url"]
        for item in existing
        if item.get("stored_file_path") and Path(item["stored_file_path"]).is_file()
    }
    for attachment in detail["attachments"]:
        if attachment["url"] in existing_urls:
            continue
        filename, mime_type, content_hash, stored_path = _download_attachment(attachment, source_id)
        database.save_attachment({
            "notice_id": stored_notice["id"],
            "source_url": attachment["url"],
            "original_filename": filename,
            "mime_type": mime_type,
            "content_hash": content_hash,
            "stored_file_path": stored_path,
        }, DB_PATH)
        attachment_count += 1
    database.touch_notice(source_url, DB_PATH)
    return not existing_notice, attachment_count


def _lock_owner() -> str:
    return f"{os.getpid()}-{uuid.uuid4()}"


def _acquire_lock(owner: str) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(minutes=30)
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM sync_state WHERE key = 'sync_lock'").fetchone()
        if row:
            try:
                previous = json.loads(row[0])
                if dt.datetime.fromisoformat(previous["expires_at"]) > now:
                    return False
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        conn.execute("""
            UPDATE sync_runs
            SET status = 'failed',
                finished_at = ?,
                error = 'Previous sync process ended before reporting completion.'
            WHERE status = 'running'
        """, (now.isoformat(timespec="seconds"),))
        conn.execute(
            "INSERT INTO sync_state (key, value) VALUES ('sync_lock', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps({"owner": owner, "expires_at": expires.isoformat()}),),
        )
        return True


def _release_lock(owner: str) -> None:
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        row = conn.execute("SELECT value FROM sync_state WHERE key = 'sync_lock'").fetchone()
        if row and json.loads(row[0]).get("owner") == owner:
            conn.execute("DELETE FROM sync_state WHERE key = 'sync_lock'")


def _renew_lock(owner: str) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(minutes=30)
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM sync_state WHERE key = 'sync_lock'").fetchone()
        if not row or json.loads(row[0]).get("owner") != owner:
            return False
        conn.execute(
            "UPDATE sync_state SET value = ? WHERE key = 'sync_lock'",
            (json.dumps({"owner": owner, "expires_at": expires.isoformat()}),),
        )
        return True


def run_sync(
    dry_run: bool = False,
    backfill: bool = False,
    max_pages: int = 3,
    retry_failures_only: bool = False,
) -> Dict[str, int]:
    database.init_db(DB_PATH)
    result = {
        "discovered": 0,
        "imported": 0,
        "duplicates": 0,
        "failed": 0,
        "attachments_found": 0,
        "attachments_stored": 0,
    }
    owner = _lock_owner()
    if not dry_run and not _acquire_lock(owner):
        raise RuntimeError("Another notice sync is already running.")
    run_id = None if dry_run else database.start_sync_run(DB_PATH)
    run_error: Optional[str] = None
    try:
        if retry_failures_only:
            for failure in database.get_sync_failures(DB_PATH):
                result["discovered"] += 1
                listing_item = {"url": failure["source_url"]}
                try:
                    listing_item = json.loads(failure["notice_json"])
                    imported, attachments = _import_notice(listing_item, dry_run)
                    result["imported"] += int(imported)
                    result["attachments_found"] += attachments
                    result["attachments_stored"] += 0 if dry_run else attachments
                    result["duplicates"] += int(not imported and attachments == 0)
                except Exception as exc:
                    result["failed"] += 1
                    if not dry_run:
                        _record_failure(
                            failure["source_url"],
                            f"{type(exc).__name__}: {exc}",
                            listing_item,
                        )
                    print(
                        f"FAILED {failure['source_url']}: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                time.sleep(REQUEST_DELAY_SECONDS)
            return result

        url: Optional[str]
        if backfill:
            url = database.get_sync_state("backfill_cursor", DB_PATH) or iost.IOST_NOTICES
            if database.get_sync_state("backfill_complete", DB_PATH):
                print("Historical backfill is already marked complete.")
                return result
        else:
            url = iost.IOST_NOTICES

        visited: set = set()
        for _ in range(max_pages):
            if not url:
                break
            if not dry_run and not _renew_lock(owner):
                raise RuntimeError("The notice sync lost its concurrency lock.")
            url = _validated_url(url)
            if url in visited:
                raise ImportErrorDetail("IoST pagination cursor repeated during import.")
            visited.add(url)
            response = _request(url)
            try:
                soup = BeautifulSoup(response.text, "html.parser")
            finally:
                response.close()
            listing = iost.parse_iost_page(soup, set())
            result["discovered"] += len(listing)
            for item in listing:
                try:
                    imported, attachments = _import_notice(item, dry_run)
                    result["attachments_found"] += attachments
                    if imported:
                        result["imported"] += 1
                        result["attachments_stored"] += 0 if dry_run else attachments
                    elif attachments:
                        result["attachments_stored"] += 0 if dry_run else attachments
                    else:
                        result["duplicates"] += 1
                except Exception as exc:
                    result["failed"] += 1
                    if not dry_run:
                        _record_failure(item["url"], f"{type(exc).__name__}: {exc}", item)
                    print(f"FAILED {item['url']}: {type(exc).__name__}: {exc}", file=sys.stderr)
                if not dry_run and not _renew_lock(owner):
                    raise RuntimeError("The notice sync lost its concurrency lock.")
                time.sleep(REQUEST_DELAY_SECONDS)
            next_url = _next_page(soup)
            if not backfill:
                url = next_url
                if not url or result["discovered"] == 0:
                    break
            elif next_url:
                if not dry_run:
                    database.set_sync_state("backfill_cursor", next_url, DB_PATH)
                url = next_url
            else:
                if not dry_run:
                    if database.get_sync_failures(DB_PATH):
                        database.set_sync_state("backfill_cursor", iost.IOST_NOTICES, DB_PATH)
                    else:
                        database.set_sync_state(
                            "backfill_complete",
                            dt.datetime.now(dt.timezone.utc).isoformat(),
                            DB_PATH,
                        )
                        with sqlite3.connect(DB_PATH, timeout=30) as conn:
                            conn.execute("DELETE FROM sync_state WHERE key = 'backfill_cursor'")
                url = None
            time.sleep(REQUEST_DELAY_SECONDS)
        return result
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if run_id is not None:
            status = (
                "failed" if run_error else
                "partial" if result["failed"] or database.get_sync_failures(DB_PATH) else
                "completed"
            )
            database.finish_sync_run(
                run_id,
                status,
                result["discovered"],
                result["imported"],
                result["duplicates"],
                result["failed"],
                result["attachments_stored"],
                run_error,
                DB_PATH,
            )
        if not dry_run:
            _release_lock(owner)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import and archive official IoST notices.")
    parser.add_argument("command", choices=("sync", "backfill", "retry-failures"))
    parser.add_argument("--dry-run", action="store_true", help="Inspect notices and attachments without saving them.")
    parser.add_argument("--max-pages", type=int, default=3, help="Page batch size; repeated backfill runs resume automatically.")
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    summary = run_sync(
        dry_run=args.dry_run,
        backfill=args.command == "backfill",
        max_pages=args.max_pages,
        retry_failures_only=args.command == "retry-failures",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

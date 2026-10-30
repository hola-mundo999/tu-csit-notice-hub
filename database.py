import sqlite3
from typing import List, Dict, Optional
import hashlib
import os
import datetime as dt
from contextlib import contextmanager

DB_PATH = os.environ.get("NOTICE_DB_PATH", "notices.db")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def _connection(db_path: str):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _notice_hash(notice: Dict) -> str:
    """Deterministic, process-independent hash for deduplication."""
    raw = (notice.get("title", "") + "|" + notice.get("publish_date", "") + "|" + notice.get("url", "")).encode()
    return notice.get("notice_hash") or hashlib.md5(raw).hexdigest()

def init_db(db_path: str = DB_PATH):
    with _connection(db_path) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_hash TEXT UNIQUE,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            semester TEXT NOT NULL,
            publish_date TEXT NOT NULL,
            url TEXT NOT NULL,
            is_urgent INTEGER DEFAULT 0,
            notified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(notices)")}
        migrations = {
            "source_id": "TEXT",
            "source_url": "TEXT",
            "source_published_at": "TEXT",
            "first_seen_at": "TEXT",
            "last_seen_at": "TEXT",
            "imported_at": "TEXT",
            "last_synced_at": "TEXT",
            "sync_status": "TEXT",
        }
        for name, column_type in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE notices ADD COLUMN {name} {column_type}")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS notices_source_id_unique
            ON notices(source_id) WHERE source_id IS NOT NULL AND source_id != ''
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS notices_source_url_unique
            ON notices(source_url) WHERE source_url IS NOT NULL AND source_url != ''
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notice_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id INTEGER NOT NULL REFERENCES notices(id),
                source_url TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT,
                content_hash TEXT,
                stored_file_path TEXT,
                downloaded_at TEXT,
                UNIQUE(notice_id, source_url, content_hash)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                discovered INTEGER NOT NULL DEFAULT 0,
                imported INTEGER NOT NULL DEFAULT 0,
                duplicates INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                attachments_stored INTEGER NOT NULL DEFAULT 0,
                error TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_failures (
                source_url TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                first_failed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_attempt_at TEXT NOT NULL,
                resolved_at TEXT,
                notice_json TEXT
            )
        """)
        failure_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_failures)")}
        if "resolved_at" not in failure_columns:
            conn.execute("ALTER TABLE sync_failures ADD COLUMN resolved_at TEXT")
        if "notice_json" not in failure_columns:
            conn.execute("ALTER TABLE sync_failures ADD COLUMN notice_json TEXT")

def save_notice(notice: Dict, db_path: str = DB_PATH) -> bool:
    """Inserts notice if not already present. Returns True if newly added."""
    notice_hash = _notice_hash(notice)
    source_url = notice.get("source_url") or notice.get("url", "")
    source_id = notice.get("source_id")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute("""
            INSERT INTO notices (
                notice_hash, title, category, semester, publish_date, url, is_urgent,
                source_id, source_url, source_published_at, first_seen_at, last_seen_at,
                imported_at, last_synced_at, sync_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, (
            notice_hash,
            notice["title"],
            notice.get("category", "General"),
            notice.get("semester", "All"),
            notice.get("publish_date") or "Undated",
            notice.get("url", source_url),
            1 if notice.get("is_urgent", notice.get("urgent")) else 0,
            source_id,
            source_url or None,
            notice.get("source_published_at") or notice.get("publish_date"),
            now,
            now,
            now,
            now,
            notice.get("sync_status", "imported"),
        ))
        return cursor.rowcount == 1

def get_notices(
    category: Optional[str] = None,
    semester: Optional[str] = None,
    search_query: Optional[str] = None,
    db_path: str = DB_PATH,
    source_only: bool = False,
) -> List[Dict]:
    records, _ = get_notice_page(
        category=category,
        semester=semester,
        search_query=search_query,
        db_path=db_path,
        source_only=source_only,
        page=1,
        page_size=1_000_000_000,
    )
    return records


def get_notice_summary(db_path: str = DB_PATH, source_only: bool = False) -> Dict[str, int]:
    conn = _connect(db_path)
    where = ""
    params = ()
    if source_only:
        where = " WHERE source_url LIKE ? OR url LIKE ?"
        params = (
            "https://iost.tu.edu.np/notices/%",
            "https://iost.tu.edu.np/notices/%",
        )
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN category = 'Exam Routine' THEN 1 ELSE 0 END) AS exam_routines,
            SUM(CASE WHEN category = 'Results' THEN 1 ELSE 0 END) AS results,
            SUM(CASE WHEN category = 'Form Fill Up' THEN 1 ELSE 0 END) AS form_fill_ups
        FROM notices{where}
        """,
        params,
    ).fetchone()
    conn.close()
    total = row["total"] or 0
    exams = row["exam_routines"] or 0
    results = row["results"] or 0
    forms = row["form_fill_ups"] or 0
    return {
        "total": total,
        "exam_routines": exams,
        "results": results,
        "form_fill_ups": forms,
        "general_notices": total - exams - results - forms,
    }


def get_notice_page(
    category: Optional[str] = None,
    semester: Optional[str] = None,
    search_query: Optional[str] = None,
    db_path: str = DB_PATH,
    source_only: bool = False,
    page: int = 1,
    page_size: int = 24,
    sort_order: str = "newest",
) -> tuple[List[Dict], int]:
    conn = _connect(db_path)
    where = ["1=1"]
    params = []

    if source_only:
        where.append("(source_url LIKE ? OR url LIKE ?)")
        params.extend((
            "https://iost.tu.edu.np/notices/%",
            "https://iost.tu.edu.np/notices/%",
        ))

    if category and category != "All":
        if category == "General Notice":
            where.append("(category = ? OR category = 'General')")
            params.append(category)
        else:
            where.append("category = ?")
            params.append(category)

    if semester and semester != "All Semesters":
        where.append("(semester = ? OR semester = 'All')")
        params.append(semester)

    if search_query:
        for term in search_query.split():
            where.append(
                "(title LIKE ? OR category LIKE ? OR semester LIKE ? OR source_id LIKE ?)"
            )
            params.extend((f"%{term}%",) * 4)

    where_sql = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM notices WHERE {where_sql}",
        params,
    ).fetchone()[0]
    offset = max(0, page - 1) * page_size
    order = (
        "COALESCE(source_published_at, publish_date) ASC, "
        "COALESCE(first_seen_at, '') DESC, id DESC"
        if sort_order == "oldest"
        else "COALESCE(source_published_at, publish_date) DESC, "
        "COALESCE(first_seen_at, '9999') ASC, id ASC"
    )
    rows = conn.execute(
        f"SELECT * FROM notices WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, page_size, offset),
    ).fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results, total


def get_notice_by_source_url(source_url: str, db_path: str = DB_PATH) -> Optional[Dict]:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notices WHERE source_url = ? OR url = ? LIMIT 1",
            (source_url, source_url),
        ).fetchone()
        return dict(row) if row else None


def touch_notice(source_url: str, db_path: str = DB_PATH) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _connection(db_path) as conn:
        conn.execute(
            "UPDATE notices SET last_seen_at = ?, last_synced_at = ? "
            "WHERE source_url = ? OR url = ?",
            (now, now, source_url, source_url),
        )
        conn.execute(
            "UPDATE sync_failures SET resolved_at = ? WHERE source_url = ?",
            (now, source_url),
        )


def get_sync_failures(db_path: str = DB_PATH) -> List[Dict]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sync_failures WHERE resolved_at IS NULL ORDER BY last_attempt_at",
        ).fetchall()
        return [dict(row) for row in rows]


def has_sync_failure(source_url: str, db_path: str = DB_PATH) -> bool:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sync_failures WHERE source_url = ? AND resolved_at IS NULL",
            (source_url,),
        ).fetchone()
        return row is not None


def save_attachment(attachment: Dict, db_path: str = DB_PATH) -> bool:
    with _connection(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO notice_attachments (
                notice_id, source_url, original_filename, mime_type,
                content_hash, stored_file_path, downloaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT DO NOTHING
        """, (
            attachment["notice_id"],
            attachment["source_url"],
            attachment["original_filename"],
            attachment.get("mime_type"),
            attachment.get("content_hash"),
            attachment.get("stored_file_path"),
        ))
        return cursor.rowcount == 1


def get_attachments(notice_id: int, db_path: str = DB_PATH) -> List[Dict]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notice_attachments WHERE notice_id = ? ORDER BY id",
            (notice_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_attachment(attachment_id: int, db_path: str = DB_PATH) -> Optional[Dict]:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notice_attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        return dict(row) if row else None


def get_sync_state(key: str, db_path: str = DB_PATH) -> Optional[str]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_sync_state(key: str, value: str, db_path: str = DB_PATH) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def start_sync_run(db_path: str = DB_PATH) -> int:
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')",
            (started_at,),
        )
        return int(cursor.lastrowid)


def finish_sync_run(
    run_id: int,
    status: str,
    discovered: int,
    imported: int,
    duplicates: int,
    failed: int,
    attachments_stored: int,
    error: Optional[str] = None,
    db_path: str = DB_PATH,
) -> None:
    finished_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _connection(db_path) as conn:
        conn.execute("""
            UPDATE sync_runs
            SET finished_at = ?, status = ?, discovered = ?, imported = ?,
                duplicates = ?, failed = ?, attachments_stored = ?, error = ?
            WHERE id = ?
        """, (
            finished_at, status, discovered, imported, duplicates, failed,
            attachments_stored, error, run_id,
        ))


def get_latest_sync_run(db_path: str = DB_PATH, status: Optional[str] = None) -> Optional[Dict]:
    with _connection(db_path) as conn:
        if status:
            row = conn.execute(
                "SELECT * FROM sync_runs WHERE status = ? ORDER BY id DESC LIMIT 1",
                (status,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

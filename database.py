import sqlite3
from typing import List, Dict, Optional
import hashlib

DB_PATH = "notices.db"

def _notice_hash(notice: Dict) -> str:
    """Deterministic, process-independent hash for deduplication."""
    raw = (notice.get("title", "") + "|" + notice.get("publish_date", "") + "|" + notice.get("url", "")).encode()
    return notice.get("notice_hash") or hashlib.md5(raw).hexdigest()

def init_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
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
    conn.commit()
    conn.close()

def save_notice(notice: Dict, db_path: str = DB_PATH) -> bool:
    """Inserts notice if not already present. Returns True if newly added."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    notice_hash = _notice_hash(notice)
    
    try:
        cursor.execute("""
        INSERT INTO notices (notice_hash, title, category, semester, publish_date, url, is_urgent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            notice_hash,
            notice["title"],
            notice.get("category", "General"),
            notice.get("semester", "All"),
            notice.get("publish_date", "Recent"),
            notice.get("url", "https://tuiost.edu.np"),
            1 if notice.get("is_urgent") else 0
        ))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_notices(category: Optional[str] = None, semester: Optional[str] = None, search_query: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM notices WHERE 1=1"
    params = []

    if category and category != "All":
        query += " AND category = ?"
        params.append(category)

    if semester and semester != "All Semesters":
        query += " AND (semester = ? OR semester = 'All')"
        params.append(semester)

    if search_query:
        query += " AND title LIKE ?"
        params.append(f"%{search_query}%")

    query += " ORDER BY id DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results

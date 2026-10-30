import hashlib
import sqlite3
import threading
from http.server import ThreadingHTTPServer

import pytest
import requests

import database
from api import document
import iost_sync


def notice(url="https://iost.tu.edu.np/notices/42", title="Published notice"):
    return {
        "source_id": "42",
        "source_url": url,
        "url": url,
        "title": title,
        "category": "General Notice",
        "semester": "All Semesters",
        "publish_date": "2026-10-26",
    }


def test_source_id_and_url_uniqueness_preserve_the_first_archive(tmp_path):
    db_path = str(tmp_path / "notices.db")
    database.init_db(db_path)
    assert database.save_notice(notice(), db_path)
    assert not database.save_notice(notice(title="Changed upstream title"), db_path)
    rows = database.get_notices(db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["title"] == "Published notice"
    assert rows[0]["source_id"] == "42"


def test_notice_page_query_limits_rows_but_returns_total_and_searches_metadata(tmp_path):
    db_path = str(tmp_path / "pages.db")
    database.init_db(db_path)
    for source_id in range(1, 6):
        item = notice(
            f"https://iost.tu.edu.np/notices/{source_id}",
            f"Published notice {source_id}",
        )
        item["source_id"] = str(source_id)
        database.save_notice(item, db_path)
    page, total = database.get_notice_page(db_path=db_path, source_only=True, page=2, page_size=2)
    assert total == 5
    assert len(page) == 2
    matched, matching_total = database.get_notice_page(
        db_path=db_path,
        source_only=True,
        search_query="42",
    )
    assert matching_total == 0
    assert matched == []
    matched, matching_total = database.get_notice_page(
        db_path=db_path,
        source_only=True,
        search_query="General Notice",
    )
    assert matching_total == 5
    assert len(matched) == 5


def test_existing_database_schema_is_migrated_without_data_loss(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE notices (
                id INTEGER PRIMARY KEY,
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
        conn.execute(
            "INSERT INTO notices (notice_hash, title, category, semester, publish_date, url) "
            "VALUES ('old-hash', 'Existing', 'General Notice', 'All Semesters', 'Undated', 'https://iost.tu.edu.np/notices/1')"
        )
    database.init_db(db_path)
    row = database.get_notices(db_path=db_path)[0]
    assert row["title"] == "Existing"
    assert "source_id" in row


def test_attachment_metadata_is_saved_and_retrievable(tmp_path):
    db_path = str(tmp_path / "attachments.db")
    database.init_db(db_path)
    database.save_notice(notice(), db_path)
    row = database.get_notice_by_source_url(notice()["url"], db_path)
    file_path = tmp_path / "42-file.pdf"
    file_path.write_bytes(b"%PDF-1.7 test")
    attachment = {
        "notice_id": row["id"],
        "source_url": "https://portal.tu.edu.np/notice/42/file.pdf",
        "original_filename": "file.pdf",
        "mime_type": "application/pdf",
        "content_hash": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "stored_file_path": str(file_path),
    }
    assert database.save_attachment(attachment, db_path)
    found = database.get_attachments(row["id"], db_path)
    assert found[0]["original_filename"] == "file.pdf"
    assert database.get_attachment(found[0]["id"], db_path)["stored_file_path"] == str(file_path)


@pytest.mark.parametrize("url", [
    "https://iost.tu.edu.np/notices/42",
    "https://portal.tu.edu.np/notice/42/file.pdf",
])
def test_only_official_https_hosts_are_allowed(url):
    assert iost_sync._validated_url(url, attachment=True) == url


@pytest.mark.parametrize("url", [
    "http://iost.tu.edu.np/notices/42",
    "https://example.com/notices/42",
    "https://127.0.0.1/notices/42",
    "https://iost.tu.edu.np.evil.example/notices/42",
])
def test_untrusted_or_non_https_hosts_are_rejected(url):
    with pytest.raises(iost_sync.ImportErrorDetail):
        iost_sync._validated_url(url)


def test_pdf_signature_validation(tmp_path):
    pdf = tmp_path / "valid.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    html_as_pdf = tmp_path / "fake.pdf"
    html_as_pdf.write_text("<html>not a PDF</html>")
    assert iost_sync._valid_signature(pdf, ".pdf")
    assert not iost_sync._valid_signature(html_as_pdf, ".pdf")


def test_archive_query_ignores_records_from_the_old_source(tmp_path, monkeypatch):
    db_path = str(tmp_path / "source-filter.db")
    database.init_db(db_path)
    database.save_notice(notice(), db_path)
    database.save_notice({
        **notice("https://tuiost.edu.np/notices/old"),
        "source_id": None,
        "title": "Old source record",
    }, db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    archived, total = iost_sync.iost.archive_notices()
    assert archived is not None
    assert total == 1
    assert [item["title"] for item in archived] == ["Published notice"]


def test_dry_run_does_not_insert_a_notice(tmp_path, monkeypatch):
    db_path = str(tmp_path / "dry-run.db")
    database.init_db(db_path)
    monkeypatch.setattr(iost_sync, "DB_PATH", db_path)

    class Response:
        is_redirect = False
        headers = {}
        text = """
          <div class="detail-page-inner">
            <h4 class="title">Published notice</h4>
            <span class="nep_date">2026-10-26</span>
          </div>
        """

        def raise_for_status(self):
            return None

        def close(self):
            return None

    def fake_get(_url, **_kwargs):
        return Response()

    monkeypatch.setattr(iost_sync.requests, "get", fake_get)
    imported, attachment_count = iost_sync._import_notice(notice(), dry_run=True)
    assert imported
    assert attachment_count == 0
    assert database.get_notices(db_path=db_path) == []


def test_document_endpoint_serves_inline_pdf_with_byte_ranges(tmp_path, monkeypatch):
    db_path = str(tmp_path / "document.db")
    storage_dir = tmp_path / "files"
    storage_dir.mkdir()
    pdf_path = storage_dir / "42-file.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\ncontent")
    database.init_db(db_path)
    database.save_notice(notice(), db_path)
    archived_notice = database.get_notice_by_source_url(notice()["url"], db_path)
    database.save_attachment({
        "notice_id": archived_notice["id"],
        "source_url": "https://portal.tu.edu.np/notice/42/file.pdf",
        "original_filename": "notice.pdf",
        "mime_type": "application/pdf",
        "content_hash": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "stored_file_path": str(pdf_path),
    }, db_path)
    attachment_id = database.get_attachments(archived_notice["id"], db_path)[0]["id"]
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(document, "STORAGE_DIR", storage_dir.resolve())

    server = ThreadingHTTPServer(("127.0.0.1", 0), document.handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = requests.get(
            f"http://127.0.0.1:{server.server_port}/api/document"
            f"?attachment_id={attachment_id}&disposition=inline",
            headers={"Range": "bytes=0-4"},
            timeout=3,
        )
        assert response.status_code == 206
        assert response.headers["Content-Type"] == "application/pdf"
        assert response.headers["Content-Range"].startswith("bytes 0-4/")
        assert response.headers["Content-Disposition"].startswith("inline;")
        assert response.content == b"%PDF-"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_notice_api_returns_server_paginated_archive_results(tmp_path, monkeypatch):
    db_path = str(tmp_path / "notices-api.db")
    database.init_db(db_path)
    for source_id in range(1, 4):
        item = notice(
            f"https://iost.tu.edu.np/notices/{source_id}",
            f"Published notice {source_id}",
        )
        item["source_id"] = str(source_id)
        database.save_notice(item, db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), iost_sync.iost.handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = requests.get(
            f"http://127.0.0.1:{server.server_port}/api/notices?page=2&page_size=2",
            timeout=3,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "archive"
        assert payload["total"] == 3
        assert payload["page"] == 2
        assert len(payload["notices"]) == 1
        assert payload["notices"][0]["title"] == "Published notice 1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

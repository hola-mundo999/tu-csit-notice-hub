"""Serve validated, locally archived notice attachments."""

import os
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import database

STORAGE_DIR = Path(os.environ.get("NOTICE_STORAGE_DIR", "notice_files")).resolve()
MAX_RANGE_BYTES = 2 * 1024 * 1024


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (Vercel entrypoint)
        params = parse_qs(urlparse(self.path).query)
        try:
            attachment_id = int(params.get("attachment_id", [""])[0])
        except ValueError:
            self.send_error(400, "A valid attachment_id is required.")
            return

        attachment = database.get_attachment(attachment_id, database.DB_PATH)
        if not attachment or not attachment.get("stored_file_path"):
            self.send_error(404, "Archived document not found.")
            return
        try:
            source = urlparse(attachment["source_url"])
            source_port = source.port
        except ValueError:
            self.send_error(404, "Archived document not found.")
            return
        if (
            source.scheme != "https"
            or source.hostname not in {"iost.tu.edu.np", "portal.tu.edu.np"}
            or source_port not in (None, 443)
            or source.username
            or source.password
        ):
            self.send_error(404, "Archived document not found.")
            return

        path = Path(attachment["stored_file_path"]).resolve()
        try:
            if os.path.commonpath((str(STORAGE_DIR), str(path))) != str(STORAGE_DIR):
                self.send_error(404, "Archived document not found.")
                return
        except ValueError:
            self.send_error(404, "Archived document not found.")
            return
        if not path.is_file():
            self.send_error(404, "Archived document not found.")
            return

        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_error(416, "Invalid byte range.")
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                suffix_size = int(match.group(2))
                start = max(0, size - suffix_size)
            if start >= size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            if end - start + 1 > MAX_RANGE_BYTES:
                end = start + MAX_RANGE_BYTES - 1
            status = 206

        filename = Path(attachment["original_filename"]).name
        disposition = "inline" if params.get("disposition", ["attachment"])[0] == "inline" else "attachment"
        if disposition == "inline" and attachment.get("mime_type") != "application/pdf":
            disposition = "attachment"
        encoded_filename = quote(filename, safe="")
        content_length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", attachment.get("mime_type") or "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename*=UTF-8''{encoded_filename}",
        )
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=86400, immutable")
        self.end_headers()
        with path.open("rb") as document:
            document.seek(start)
            remaining = content_length
            while remaining:
                chunk = document.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

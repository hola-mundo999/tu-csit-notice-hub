"""Compatibility wrapper for fetching current notices from the official IoST site."""

import hashlib
from typing import Dict, List, Optional, Tuple

from api import notices as iost


class TUScraper:
    BASE_URL = iost.IOST
    NOTICES_URL = iost.IOST_NOTICES
    LAST_ERROR: Optional[str] = None

    @classmethod
    def fetch_live_notices(cls) -> Tuple[List[Dict], Optional[str]]:
        """Return notices from IoST only; never substitute fabricated fallback records."""
        cls.LAST_ERROR = None
        try:
            found = iost.scrape_iost()
        except Exception as exc:
            cls.LAST_ERROR = f"Unable to reach official IoST notices: {type(exc).__name__}: {exc}"
            return [], cls.LAST_ERROR

        notices = []
        for item in found:
            notices.append({
                "notice_hash": hashlib.md5(f"{item['title']}|{item['url']}".encode("utf-8")).hexdigest(),
                "source_id": item.get("source_id"),
                "source_url": item["url"],
                "title": item["title"],
                "category": item["category"],
                "semester": item["semester"],
                "publish_date": item.get("publish_date") or "Undated",
                "url": item["url"],
                "is_urgent": item["urgent"],
            })
        if not notices:
            cls.LAST_ERROR = "The official IoST listing contained no recognizable notices."
        return notices, cls.LAST_ERROR

    @classmethod
    def _classify_notice(cls, text: str, url: str) -> Dict:
        meta = iost.classify(text)
        return {
            "notice_hash": hashlib.md5((text + url).encode("utf-8")).hexdigest(),
            "source_url": url,
            "title": text[:180],
            "category": meta["category"],
            "semester": meta["semester"],
            "publish_date": "Undated",
            "url": url,
            "is_urgent": meta["urgent"],
        }

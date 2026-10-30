"""The current IoST site is a different page from the one this feed started on.

The fixture is a saved copy of https://iost.tu.edu.np/notices, which is where
IoST has published since 2081. tuiost.edu.np stopped taking notices in 2023,
so parsing the new markup is what keeps the feed from going stale again.
"""
import importlib.util
import pathlib

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "iost_notices.html"

spec = importlib.util.spec_from_file_location("notices", ROOT / "api" / "notices.py")
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


def load_soup():
    return BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")


def test_parses_the_current_iost_layout():
    found = notices.parse_iost_page(load_soup(), set())
    assert len(found) >= 5
    for item in found:
        assert item["url"].startswith("https://iost.tu.edu.np/notices/")
        assert len(item["title"]) > 12
        assert item["publish_date"] is None or len(item["publish_date"]) == 10


def test_dates_are_current_not_the_2023_archive():
    found = notices.parse_iost_page(load_soup(), set())
    dates = [item["publish_date"] for item in found if item["publish_date"]]
    assert dates, "the new site must carry publication dates"
    assert max(dates) >= "2026-01-01", "the feed would look three years stale"


def test_duplicates_within_a_page_are_dropped():
    seen = set()
    first = notices.parse_iost_page(load_soup(), seen)
    second = notices.parse_iost_page(load_soup(), seen)
    assert first and not second


def test_exam_schedule_is_classified_as_a_routine():
    item = notices.build_notice(
        "B.Sc.CSIT and Bachelor in Information Technology (BIT) VIII Semester-2078 Make Up Exam Schedule",
        "https://iost.tu.edu.np/notices/13659",
        "2026-07-03",
        "2026-07-03",
        "live",
    )
    assert item["category"] == "Exam Routine"
    assert item["semester"] == "8th Sem"


def test_nepali_titles_are_classified_too():
    form_fill = notices.classify("२०८३ मा B.Sc. मा भर्नाका लागि आवेदन फाराम भर्ने सम्बन्धी सूचना")
    assert form_fill["category"] == "Form Fill Up"

    result = notices.classify("B.Sc.CSIT V Semester-2080 Exam Result")
    assert result["category"] == "Results"


class _Response:
    def __init__(self, text):
        self.text = text
        self.headers = {}
        self.status_code = 200
        self.is_redirect = False

    def raise_for_status(self):
        return None

    def close(self):
        return None


def test_scrape_reads_the_current_site_first(monkeypatch):
    html = FIXTURE.read_text(encoding="utf-8")

    def fake_get(url, **_kwargs):
        if "iost.tu.edu.np" in url:
            return _Response(html)
        raise AssertionError("the legacy portal should not be consulted")

    monkeypatch.setattr(notices.requests, "get", fake_get)
    found, site, error = notices.scrape()
    assert site == "iost.tu.edu.np"
    assert error is None
    assert found[0]["publish_date"] >= found[-1]["publish_date"]


def test_scrape_preserves_source_order_for_notices_with_the_same_date(monkeypatch):
    first_page = """
      <div class="recent-post-wrapper">
        <div class="date"><span class="nep_date">2026-10-26</span></div>
        <div class="detail"><a href="/notices/15953"><h5>B.Sc.CSIT exam schedule</h5></a></div>
      </div>
      <div class="recent-post-wrapper">
        <div class="date"><span class="nep_date">2026-10-26</span></div>
        <div class="detail"><a href="/notices/15952"><h5>Re-totaling result</h5></a></div>
      </div>
      <ul class="pagination"><li><a class="page-link" href="?cursor=older">Next »</a></li></ul>
    """
    second_page = """
      <div class="recent-post-wrapper">
        <div class="date"><span class="nep_date">2026-10-14</span></div>
        <div class="detail"><a href="/notices/15925"><h5>Older exam result</h5></a></div>
      </div>
    """

    def fake_get(url, **_kwargs):
        if "cursor=older" in url:
            return _Response(second_page)
        if url == notices.IOST_NOTICES:
            return _Response(first_page)
        raise AssertionError(f"Unexpected listing URL: {url}")

    monkeypatch.setattr(notices.requests, "get", fake_get)

    found = notices.scrape_iost(max_pages=2)

    assert [item["source_id"] for item in found] == ["15953", "15952", "15925"]


def test_scrape_does_not_substitute_the_stale_legacy_site(monkeypatch):
    def fake_get(url, **_kwargs):
        if "iost.tu.edu.np" in url:
            raise requests.ConnectionError("connection refused")
        raise AssertionError("an unapproved legacy notice source was consulted")

    monkeypatch.setattr(notices.requests, "get", fake_get)
    monkeypatch.setattr(notices, "MAX_RETRIES", 1)
    found, site, error = notices.scrape()
    assert found == []
    assert site == "iost.tu.edu.np"
    assert "ConnectionError" in error


def test_detail_parser_extracts_title_date_and_attachment():
    soup = BeautifulSoup("""
      <div class="detail-page-inner">
        <h4 class="title">B.Sc.CSIT exam schedule</h4>
        <span class="nep_date">2026-10-26</span>
      </div>
      <table><tbody><tr>
        <td>Exam schedule</td><td>pdf</td>
        <td><a href="https://portal.tu.edu.np/notice/12/schedule.pdf">Download</a></td>
      </tr></tbody></table>
    """, "html.parser")
    parsed = notices.parse_iost_detail(soup, "https://iost.tu.edu.np/notices/12")
    assert parsed["title"] == "B.Sc.CSIT exam schedule"
    assert parsed["publish_date"] == "2026-10-26"
    assert parsed["attachments"] == [{
        "url": "https://portal.tu.edu.np/notice/12/schedule.pdf",
        "filename": "schedule.pdf",
        "file_type": "pdf",
    }]


def test_detail_parser_ignores_attachment_links_on_untrusted_hosts():
    soup = BeautifulSoup("""
      <div class="detail-page-inner"><h4 class="title">Notice title</h4></div>
      <table><tbody><tr><td>file.pdf</td><td>pdf</td>
      <td><a href="https://example.com/file.pdf">Download</a></td></tr></tbody></table>
    """, "html.parser")
    parsed = notices.parse_iost_detail(soup, "https://iost.tu.edu.np/notices/12")
    assert parsed["attachments"] == []

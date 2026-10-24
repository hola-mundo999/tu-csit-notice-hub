"""The current IoST site is a different page from the one this feed started on.

The fixture is a saved copy of https://iost.tu.edu.np/notices, which is where
IoST has published since 2081. tuiost.edu.np stopped taking notices in 2023,
so parsing the new markup is what keeps the feed from going stale again.
"""
import importlib.util
import pathlib

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

    def raise_for_status(self):
        return None


def test_scrape_reads_the_current_site_first(monkeypatch):
    html = FIXTURE.read_text(encoding="utf-8")

    def fake_get(url, **kwargs):
        if "iost.tu.edu.np" in url:
            return _Response(html)
        raise AssertionError("the legacy portal should not be consulted")

    monkeypatch.setattr(notices.requests, "get", fake_get)
    found, site, error = notices.scrape()
    assert site == "iost.tu.edu.np"
    assert error is None
    assert found[0]["publish_date"] >= found[-1]["publish_date"]


def test_scrape_falls_back_when_the_new_site_is_unreachable(monkeypatch):
    legacy = """
    <div class="feature-content">
      <div class="mt-3">
        <a href="/storage/notice/routine.pdf"><b>B.Sc.CSIT Exam Routine</b></a>
        <small>26th Jul, 2026</small>
      </div>
    </div>
    """

    def fake_get(url, **kwargs):
        if "iost.tu.edu.np" in url:
            raise OSError("connection refused")
        return _Response(legacy)

    monkeypatch.setattr(notices.requests, "get", fake_get)
    found, site, error = notices.scrape()
    assert found, "the feed must keep working on the legacy portal"
    assert site == "tuiost.edu.np"
    assert found[0]["publish_date"] == "2026-07-26"

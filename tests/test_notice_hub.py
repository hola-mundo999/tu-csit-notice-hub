import os
import tempfile

from database import init_db, save_notice, get_notices, _notice_hash
from scraper import TUScraper


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    return path


# --------------------------------------------------------------------- #
# Database: deterministic deduplication
# --------------------------------------------------------------------- #
def test_save_and_get_notice_roundtrip():
    path = make_db()
    n = {
        "notice_hash": "tu_test_001",
        "title": "B.Sc. CSIT 4th Semester Exam Routine Published",
        "category": "Exam Routine",
        "semester": "4th Sem",
        "publish_date": "2081-06-24",
        "url": "https://iost.tu.edu.np/notices/1",
        "is_urgent": True,
    }
    assert save_notice(n, path) is True
    assert save_notice(n, path) is False  # duplicate by hash
    rows = get_notices(db_path=path)
    assert len(rows) == 1
    assert rows[0]["title"] == n["title"]
    assert rows[0]["is_urgent"] == 1


def test_notice_hash_is_deterministic_across_processes():
    """The old str(hash()) fallback was randomized per Python process."""
    n = {
        "title": "B.Sc. CSIT 4th Semester Exam Routine Published",
        "publish_date": "2081-06-24",
        "url": "https://iost.tu.edu.np/notices/1",
    }
    h1 = _notice_hash(n)
    h2 = _notice_hash(n)
    assert h1 == h2
    assert len(h1) == 32  # md5 hexdigest


def test_duplicate_without_explicit_hash_still_detected():
    path = make_db()
    n = {
        "title": "Notice Without Hash",
        "category": "Results",
        "semester": "6th Sem",
        "publish_date": "2081-06-18",
        "url": "https://iost.tu.edu.np/notices/2",
        "is_urgent": False,
    }
    assert save_notice(n, path) is True
    assert save_notice(n, path) is False  # same content -> same hash


def test_get_notices_filters_by_category_and_semester():
    path = make_db()
    save_notice({
        "notice_hash": "h1", "title": "Routine 4th", "category": "Exam Routine",
        "semester": "4th Sem", "publish_date": "2081-06-24",
        "url": "https://iost.tu.edu.np/notices/n1", "is_urgent": True,
    }, path)
    save_notice({
        "notice_hash": "h2", "title": "Result 6th", "category": "Results",
        "semester": "6th Sem", "publish_date": "2081-06-18",
        "url": "https://iost.tu.edu.np/notices/n2", "is_urgent": True,
    }, path)
    assert len(get_notices(category="Exam Routine", db_path=path)) == 1
    assert len(get_notices(semester="4th Sem", db_path=path)) == 1


def test_get_notices_search_query():
    path = make_db()
    save_notice({
        "notice_hash": "h3", "title": "Back Exam Form Fill Up Notice",
        "category": "Form Fill Up", "semester": "All Semesters",
        "publish_date": "2081-06-10", "url": "https://iost.tu.edu.np/notices/n3", "is_urgent": False,
    }, path)
    assert len(get_notices(search_query="Back Exam", db_path=path)) == 1
    assert get_notices(search_query="nonexistent", db_path=path) == []


# --------------------------------------------------------------------- #
# Scraper: classification and semester detection
# --------------------------------------------------------------------- #
def test_classify_exam_routine_urgent():
    n = TUScraper._classify_notice(
        "B.Sc. CSIT 4th Semester Exam Routine Published", "https://iost.tu.edu.np/notices/1"
    )
    assert n["category"] == "Exam Routine"
    assert n["is_urgent"] is True
    assert n["semester"] == "4th Sem"


def test_classify_results_urgent():
    n = TUScraper._classify_notice(
        "Final results published for 6th semester", "https://iost.tu.edu.np/notices/2"
    )
    assert n["category"] == "Results"
    assert n["is_urgent"] is True


def test_classify_form_fillup():
    n = TUScraper._classify_notice(
        "Examination form fill-up deadline extended", "https://iost.tu.edu.np/notices/3"
    )
    assert n["category"] == "Form Fill Up"
    assert n["semester"] == "All Semesters"


def test_classify_general():
    n = TUScraper._classify_notice(
        "Guest lecture on artificial intelligence next week", "https://iost.tu.edu.np/notices/4"
    )
    assert n["category"] == "General Notice"
    assert n["is_urgent"] is False


def test_semester_1st_does_not_match_21st():
    n = TUScraper._classify_notice(
        "21st century computing guest lecture", "https://iost.tu.edu.np/notices/5"
    )
    assert n["semester"] == "All Semesters"


def test_hash_deterministic_across_calls():
    n1 = TUScraper._classify_notice("Some notice title", "https://iost.tu.edu.np/notices/6")
    n2 = TUScraper._classify_notice("Some notice title", "https://iost.tu.edu.np/notices/6")
    assert n1["notice_hash"] == n2["notice_hash"]


# --------------------------------------------------------------------- #
# Curated notices
# --------------------------------------------------------------------- #

"""Derived notice categories and programme labels; source titles remain unchanged."""

import re
from typing import Dict, List


CATEGORY_ORDER = (
    "Exam Routine",
    "Exam Centre",
    "Examination",
    "Results",
    "Admission",
    "Form Fill Up",
    "General Notice",
)

_CATEGORY_RULES = (
    ("Results", re.compile(
        r"\b(?:re[\s-]*total(?:ing)?|retotal(?:ing)?|rechecking|result|results|pass list|topper)\b"
        r"|नतिजा|नतीजा|फलाफल",
        re.IGNORECASE,
    )),
    ("Exam Centre", re.compile(
        r"\b(?:exam(?:ination)?|make[\s-]*up exam)\s+(?:center|centre)s?\b"
        r"|परीक्षा\s*केन्द्र",
        re.IGNORECASE,
    )),
    ("Form Fill Up", re.compile(
        r"\b(?:form\s*fill[\s-]*up|fill[\s-]*up\s+form|exam(?:ination)?\s+form)\b"
        r"|फाराम भर्ने|फारम भर्ने|आवेदन फाराम",
        re.IGNORECASE,
    )),
    ("Admission", re.compile(
        r"\b(?:admission|entrance|enrol(?:l)?ment)\b|भर्ना|प्रवेश परीक्षा",
        re.IGNORECASE,
    )),
    ("Exam Routine", re.compile(
        r"\b(?:exam(?:ination)?\s+(?:routine|schedule|time[\s-]*table|timetable)"
        r"|(?:routine|schedule|time[\s-]*table|timetable)\s+of\s+(?:the\s+)?exam"
        r"|make[\s-]*up exam\s+(?:routine|schedule))\b"
        r"|परीक्षा\s*तालिका",
        re.IGNORECASE,
    )),
    ("Examination", re.compile(
        r"\bexam(?:ination)?\b|परीक्षा",
        re.IGNORECASE,
    )),
)

_PROGRAMME_RULES = (
    ("B.Sc. CSIT", re.compile(
        r"\bb\.?\s*sc\.?\s*csit\b"
        r"|\bbachelor\s+(?:of\s+science|in)\s+computer\s+science\s+and\s+information\s+technology\b"
        r"|\bcomputer\s+science\s+and\s+information\s+technology\b",
        re.IGNORECASE,
    )),
    ("BIT", re.compile(
        r"\bbachelor\s+in\s+information\s+technology\b|(?<![A-Za-z])BIT(?![A-Za-z])"
    )),
    ("Bachelor in Data Science", re.compile(
        r"\bbachelor\s+in\s+data\s+science\b|\bb\.?\s*sc\.?\s+data\s+science\b",
        re.IGNORECASE,
    )),
    ("Bachelor in Mathematical Science", re.compile(
        r"\bbachelor\s+in\s+mathematical\s+science\b", re.IGNORECASE
    )),
    ("B.Tech. Food Technology", re.compile(
        r"\bb\.?\s*tech\.?\s*\(?\s*food\s+technology\b", re.IGNORECASE
    )),
    ("M.Sc. Biodiversity and Environmental Management", re.compile(
        r"\bm\.?\s*sc\.?\s+biodiversity\s+and\s+environmental\s+management\b",
        re.IGNORECASE,
    )),
    ("M.Sc. Environmental Health in Disaster", re.compile(
        r"\bm\.?\s*sc\.?\s+environmental\s+health(?:\s+in\s+disaster)?\b",
        re.IGNORECASE,
    )),
    ("M.Sc. Hydrology and Meteorology", re.compile(
        r"\bm\.?\s*sc\.?\s+hydrology\s*(?:&|and)\s*meteorology\b", re.IGNORECASE
    )),
    ("M.Sc. Engineering Geology", re.compile(
        r"\bm\.?\s*sc\.?\s+engineering\s+geology\b", re.IGNORECASE
    )),
    ("M.Sc. Environmental Science", re.compile(
        r"\bm\.?\s*sc\.?\s+environmental\s+science\b", re.IGNORECASE
    )),
    ("M.Sc. Food Technology", re.compile(
        r"\bm\.?\s*sc\.?\s+food\s+technology\b", re.IGNORECASE
    )),
    ("M.Sc. Biotechnology", re.compile(
        r"\bm\.?\s*sc\.?\s+biotechnology\b", re.IGNORECASE
    )),
    ("M.Sc. Microbiology", re.compile(
        r"\bm\.?\s*sc\.?\s+microbiology\b", re.IGNORECASE
    )),
    ("M.Sc. Mathematics", re.compile(
        r"\bm\.?\s*sc\.?\s+mathematics\b", re.IGNORECASE
    )),
    ("M.Sc. Statistics", re.compile(
        r"\bm\.?\s*sc\.?\s+statistics\b", re.IGNORECASE
    )),
    ("M.Sc. Chemistry", re.compile(
        r"\bm\.?\s*sc\.?\s+chemistry\b", re.IGNORECASE
    )),
    ("M.Sc. Zoology", re.compile(
        r"\bm\.?\s*sc\.?\s+zoology\b", re.IGNORECASE
    )),
    ("M.Sc. Physics", re.compile(
        r"\bm\.?\s*sc\.?\s+physics\b", re.IGNORECASE
    )),
    ("M.Sc. Botany", re.compile(
        r"\bm\.?\s*sc\.?\s+botany\b", re.IGNORECASE
    )),
    ("M.Sc. Geology", re.compile(
        r"\bm\.?\s*sc\.?\s+geology\b", re.IGNORECASE
    )),
    ("Ph.D.", re.compile(
        r"\bph\.?\s*d\.?\b|विद्यावारिधि", re.IGNORECASE
    )),
)


def programmes_for(title: str) -> List[str]:
    """Return only explicit programme names found in the unmodified title."""
    return [name for name, pattern in _PROGRAMME_RULES if pattern.search(title or "")]


def classify(title: str) -> Dict[str, object]:
    text = title or ""
    category = "General Notice"
    for candidate, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            category = candidate
            break

    semester = "All Semesters"
    lower = text.lower()
    semester_patterns = (
        ("8th Sem", r"\b(?:8th|eighth|viii)\s+sem"),
        ("7th Sem", r"\b(?:7th|seventh|vii)\s+sem"),
        ("6th Sem", r"\b(?:6th|sixth|vi)\s+sem"),
        ("5th Sem", r"\b(?:5th|fifth|v)\s+sem"),
        ("4th Sem", r"\b(?:4th|fourth|iv)\s+sem"),
        ("3rd Sem", r"\b(?:3rd|third|iii)\s+sem"),
        ("2nd Sem", r"\b(?:2nd|second|ii)\s+sem"),
        ("1st Sem", r"\b(?:1st|first|i)\s+sem"),
    )
    for name, pattern in semester_patterns:
        if re.search(pattern, lower):
            semester = name
            break

    urgent = (
        category in {"Exam Routine", "Exam Centre", "Results"}
        or bool(re.search(r"\b(?:urgent|last date|deadline|due date)\b", text, re.IGNORECASE))
    )
    return {
        "category": category,
        "semester": semester,
        "urgent": urgent,
        "programmes": programmes_for(text),
    }

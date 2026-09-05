"""Structure-aware chunker for New Jersey Administrative Code (NJAC) exports,
as sketched and validated in NJ/eval/chunking_strategy.md and
NJ/eval/chunk_prototype.py against njac_5_23_12.pdf.

Key gotcha (see NJ/eval/chunk_prototype.py docstring for the discovery):
these PDFs repeat a boilerplate header block on every page, so the only
reliable per-section boundary is the "End of Document" marker.

This module is now a thin NJAC-specific configuration of the shared engine
in _legal_doc.py (see that module's docstring for why it was split out --
statute.py configures the same engine for a structurally-identical but
differently-delimited document format)."""

import re

from ._legal_doc import LegalDocConfig, chunk_legal_document
from ._legal_doc import _dedupe_chunk_ids, _split_on  # re-exported for tests/internal reuse

# Subchapter number is usually pure digits (5:23-12) but some subchapters are
# letter-suffixed (5:23-3A, 5:23-4A/4B/4C/4D) -- found via real failures on
# njac_5_23_3A/4A/4D.pdf, which have real "§ 5:23-3A.1 Scope"-style headings
# that a digits-only pattern silently matched zero times (chunker fell
# through to "no extractable text", which was the wrong diagnosis -- see
# docs/AllDevFlow.md Phase 2 notes).
SUBCHAPTER_NUM_RE = r"5:23-\d+[A-Za-z]?(?:\.\d+)?"
SECTION_HEADING_RE = re.compile(rf"^§\s*({SUBCHAPTER_NUM_RE})\s+(.+)$", re.MULTILINE)
LETTERED_SUB_RE = re.compile(r"(?m)^\(([a-z])\)\s")
NUMBERED_SUB_RE = re.compile(r"(?m)^(\d+)\.\s")
# One level below a numbered item: NJAC's subcode-adoption sections (Building,
# Plumbing, Electrical, ... One- and two-family dwelling subcode) each adopt
# a model code, then list dozens of unrelated NJ amendments to it marked this
# way -- see LegalDocConfig.roman_sub_re's docstring and docs/AllDevFlow.md's
# "subcode-amendment lists dilute embeddings" investigation, 2026-09-05.
ROMAN_SUB_RE = re.compile(r"(?m)^([ivxlcdm]+)\.\s")
CROSSREF_RE = re.compile(rf"N\.J\.A\.C\.\s*{SUBCHAPTER_NUM_RE}(?:\([a-z0-9]+\))*")
STANDARD_REF_RE = re.compile(r"ASME\s+A1[0-9]\.\d(?:-\d{4})?|ICC\s+A117\.1")

NJAC_DETECT_RE = re.compile(r"N\.J\.A\.C\.\s*5:23|New Jersey Administrative Code")

PAGE_BOILERPLATE_PATTERNS = [
    re.compile(
        r"This file includes all Regulations adopted and published through the New Jersey Register,\s*Vol\.\s*\d+\s*No\.\s*\d+,\s*\n.*?\d{4}\n",
        re.DOTALL,
    ),
    re.compile(
        r"NJ - New Jersey Administrative Code\s*>\s*TITLE 5\. COMMUNITY AFFAIRS\s*>\s*CHAPTER 23\. UNIFORM\s*\nCONSTRUCTION CODE\s*>\s*SUBCHAPTER 12\. ELEVATOR SAFETY SUBCODE\n?"
    ),
    re.compile(r"^N\.J\.A\.C\.\s*5:23-\d+(?:\.\d+)?\s*$", re.MULTILINE),
    re.compile(r"^Page \d+ of \d+\s*$", re.MULTILINE),
]

_CONFIG = LegalDocConfig(
    citation_prefix="N.J.A.C.",
    section_chunk_type="njac_section",
    history_chunk_type="njac_history",
    section_heading_re=SECTION_HEADING_RE,
    lettered_sub_re=LETTERED_SUB_RE,
    numbered_sub_re=NUMBERED_SUB_RE,
    page_boilerplate_patterns=PAGE_BOILERPLATE_PATTERNS,
    cross_ref_res=[CROSSREF_RE, STANDARD_REF_RE],
    roman_sub_re=ROMAN_SUB_RE,
)


def looks_like_njac(full_text: str) -> bool:
    return bool(NJAC_DETECT_RE.search(full_text[:2000]))


def njac_chunk(doc_id: str, full_text: str) -> list[dict]:
    return chunk_legal_document(doc_id, full_text, _CONFIG)

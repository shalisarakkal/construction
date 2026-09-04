"""Structure-aware chunker for LexisNexis-exported "New Jersey Annotated
Statutes" PDFs (e.g. 52_27D_119.pdf, the State Uniform Construction Code
Act). Configures the shared engine in _legal_doc.py -- see that module's
docstring for why it's shared with njac.py rather than duplicated: this
format turned out to have the exact same per-section structure (repeated
page boilerplate, "History", "Annotations", "End of Document"), just with
different lettered/numbered subsection delimiters ("a." + "(1)" instead of
"(a)" + "1.").

Found via docs/AllDevFlow.md's 2026-09-04 investigation: this document was
previously routed through the generic (word-count) chunker, which has zero
structural awareness -- case-law annotations (the bulk of this document's
page count) were being chunked as undifferentiated prose right alongside
the actual short operative statute text, polluting retrieval (confirmed: a
pure-annotation chunk, no operative content at all, was one of the top-3
results for an unrelated real query before this fix). "Annotations" content
is dropped entirely here (same as njac.py) rather than indexed separately --
case-law commentary about a statute is a different kind of content than the
statute's own text or its enactment history, and was the concrete source of
the retrieval pollution found."""

import re

from ._legal_doc import LegalDocConfig, chunk_legal_document

STATUTE_NUM_RE = r"52:27D-[\d.]+[A-Za-z]?"
SECTION_HEADING_RE = re.compile(rf"^§\s*({STATUTE_NUM_RE})\.\s+(.+)$", re.MULTILINE)
LETTERED_SUB_RE = re.compile(r"(?m)^([a-z])\.\s")
NUMBERED_SUB_RE = re.compile(r"(?m)^\((\d+)\)\s")
CROSSREF_RE = re.compile(rf"N\.J\.\s*Stat\.(?:\s*Ann\.)?\s*§\s*{STATUTE_NUM_RE}")

STATUTE_DETECT_RE = re.compile(r"LexisNexis.{0,3}\s*New Jersey Annotated Statutes")

PAGE_BOILERPLATE_PATTERNS = [
    # Bare citation header line, e.g. "N.J. Stat. § 52:27D-124e"
    re.compile(rf"^N\.J\.\s*Stat\.\s*§\s*{STATUTE_NUM_RE}\s*$", re.MULTILINE),
    # "Current through New Jersey ..." register-currency line -- changes with
    # every new legislative session, so matched by prefix rather than a
    # fixed date/session string.
    re.compile(r"^Current through New Jersey .+$", re.MULTILINE),
    # Multi-line LexisNexis breadcrumb (Title > Subtitle > Chapter > Article),
    # different per section since it names that section's own chapter/
    # article -- matched structurally (from "LexisNexis...Annotated
    # Statutes" up to the next true line-start heading) rather than as fixed
    # text. Deliberately anchored on "^§\s" (line-start, single §) rather
    # than a bare lookahead for "§", since the breadcrumb itself sometimes
    # embeds a mid-line "§§ 52:27D-32 – 52:27D-521" range reference that a
    # bare "§" lookahead would wrongly stop at.
    re.compile(r"LexisNexis.{0,3}\s*New Jersey Annotated Statutes\s*>.*?(?=^§\s)", re.DOTALL | re.MULTILINE),
    re.compile(r"^Page \d+ of \d+\s*$", re.MULTILINE),
    # Trailing "LexisNexis(R) New Jersey Annotated Statutes / Copyright ..."
    # footer. Usually swept up by _legal_doc's Annotations-stripping (which
    # starts at "\nAnnotations\n" and drops everything after), but 58 of 134
    # sections in this corpus have no Annotations block at all -- found
    # live: this footer was leaking straight into the History chunk for
    # those sections (e.g. 52:27D-122.1) with no "Annotations" label ahead
    # of it to trigger the usual stripping. Stripped unconditionally here
    # instead, before the History/Annotations split ever happens.
    re.compile(r"LexisNexis.{0,3}\s*New Jersey Annotated Statutes\s*\n\s*Copyright.*?rights reserved\.?\s*", re.DOTALL),
]

_CONFIG = LegalDocConfig(
    citation_prefix="N.J. Stat. §",
    section_chunk_type="statute_section",
    history_chunk_type="statute_history",
    section_heading_re=SECTION_HEADING_RE,
    lettered_sub_re=LETTERED_SUB_RE,
    numbered_sub_re=NUMBERED_SUB_RE,
    page_boilerplate_patterns=PAGE_BOILERPLATE_PATTERNS,
    cross_ref_res=[CROSSREF_RE],
)


def looks_like_statute(full_text: str) -> bool:
    return bool(STATUTE_DETECT_RE.search(full_text[:2000]))


def statute_chunk(doc_id: str, full_text: str) -> list[dict]:
    return chunk_legal_document(doc_id, full_text, _CONFIG)

"""Structure-aware chunker for New Jersey Administrative Code (NJAC) exports,
as sketched and validated in NJ/eval/chunking_strategy.md and
NJ/eval/chunk_prototype.py against njac_5_23_12.pdf.

Key gotcha (see NJ/eval/chunk_prototype.py docstring for the discovery):
these PDFs repeat a boilerplate header block on every page, so the only
reliable per-section boundary is the "End of Document" marker.

Recursive split order when a section is too large:
  1. whole section (if <= MAX_CHUNK_WORDS)
  2. split on lettered subsections (a)(b)(c)
  3. split an oversized lettered subsection further on numbered items 1. 2. 3.
     (this level was a known gap in the original prototype; implemented here)
"""

import re

END_OF_DOC_RE = re.compile(r"\bEnd of Document\b")
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
HISTORY_SPLIT_RE = re.compile(r"\n\s*History\s*\n", re.IGNORECASE)
CROSSREF_RE = re.compile(rf"N\.J\.A\.C\.\s*{SUBCHAPTER_NUM_RE}(?:\([a-z0-9]+\))*")
STANDARD_REF_RE = re.compile(r"ASME\s+A1[0-9]\.\d(?:-\d{4})?|ICC\s+A117\.1")

MAX_CHUNK_WORDS = 500

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


def looks_like_njac(full_text: str) -> bool:
    return bool(NJAC_DETECT_RE.search(full_text[:2000]))


def _extract_references(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    refs = set(CROSSREF_RE.findall(flat)) | set(STANDARD_REF_RE.findall(flat))
    return sorted(refs)


def _make_chunk(doc_id: str, citation: str, section_title: str, text: str) -> dict:
    return {
        "chunk_id": f"{doc_id}__{citation.replace('N.J.A.C. ', '')}",
        "doc_id": doc_id,
        "chunk_type": "njac_section",
        "citation": citation,
        "section_title": section_title,
        "page_number": None,
        "text": text,
        "word_count": len(text.split()),
        "references": _extract_references(text),
    }


def _split_into_raw_sections(full_text: str) -> list[str]:
    pieces = END_OF_DOC_RE.split(full_text)
    return [p.strip() for p in pieces if p.strip()]


def _strip_page_boilerplate(raw_section: str) -> str:
    text = raw_section
    for pattern in PAGE_BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    return text


def _dedupe_repeated_heading(text: str, citation_num: str, title: str) -> str:
    heading_line = f"§ {citation_num} {title}"
    first_idx = text.find(heading_line)
    if first_idx == -1:
        return text
    before = text[: first_idx + len(heading_line)]
    after = text[first_idx + len(heading_line):]
    after = after.replace(heading_line, "")
    return before + after


def _split_on(regex: re.Pattern, text: str) -> list[str]:
    idxs = [m.start() for m in regex.finditer(text)]
    if not idxs:
        return [text]
    idxs.append(len(text))
    return [text[idxs[i]: idxs[i + 1]].strip() for i in range(len(idxs) - 1)]


def _chunk_lettered_piece(doc_id: str, citation_num: str, title: str, header: str, piece: str) -> list[dict]:
    """piece is one (a)/(b)/(c) block (or the whole section if no letters
    were found). Split further on numbered items if still too large."""
    letter_match = re.match(r"^\(([a-z])\)", piece)
    letter = letter_match.group(1) if letter_match else "intro"
    sub_citation = f"{citation_num}({letter})" if letter_match else citation_num
    prefixed = f"{header} {sub_citation}\n{piece}"

    if len(prefixed.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, f"N.J.A.C. {sub_citation}", title, prefixed)]

    # level 3: split on numbered items, regrouping consecutive short ones
    # up to MAX_CHUNK_WORDS instead of one chunk per item
    numbered_pieces = _split_on(NUMBERED_SUB_RE, piece)
    if len(numbered_pieces) <= 1:
        # nothing to split on further; keep as one oversized chunk rather
        # than lose content
        return [_make_chunk(doc_id, f"N.J.A.C. {sub_citation}", title, prefixed)]

    chunks = []
    group: list[str] = []
    group_words = 0
    group_start_num = None

    def flush():
        nonlocal group, group_words, group_start_num
        if not group:
            return
        num_match = re.match(r"^(\d+)\.", group[0])
        start_num = num_match.group(1) if num_match else group_start_num or "?"
        item_citation = f"{sub_citation}.{start_num}" if len(group) == 1 else f"{sub_citation}.{start_num}+"
        text = f"{header} {item_citation}\n" + "\n".join(group)
        chunks.append(_make_chunk(doc_id, f"N.J.A.C. {item_citation}", title, text))
        group = []
        group_words = 0

    for item in numbered_pieces:
        words = len(item.split())
        if group_words + words > MAX_CHUNK_WORDS and group:
            flush()
        group.append(item)
        group_words += words
    flush()
    return chunks


def _chunk_section(doc_id: str, citation_num: str, title: str, operative_text: str) -> list[dict]:
    header = f"N.J.A.C. {citation_num} — {title}"
    full_with_header = f"{header}\n{operative_text}"

    if len(full_with_header.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, f"N.J.A.C. {citation_num}", title, full_with_header)]

    chunks = []
    for piece in _split_on(LETTERED_SUB_RE, operative_text):
        chunks.extend(_chunk_lettered_piece(doc_id, citation_num, title, header, piece))
    return chunks


def njac_chunk(doc_id: str, full_text: str) -> list[dict]:
    raw_sections = _split_into_raw_sections(full_text)
    all_chunks: list[dict] = []

    for raw in raw_sections:
        m = SECTION_HEADING_RE.search(raw)
        if not m:
            continue
        citation_num, title = m.group(1), m.group(2).strip()

        cleaned = _strip_page_boilerplate(raw)
        cleaned = _dedupe_repeated_heading(cleaned, citation_num, title)

        parts = HISTORY_SPLIT_RE.split(cleaned, maxsplit=1)
        operative_text = parts[0].strip()
        operative_text = re.sub(
            re.escape(f"§ {citation_num} {title}"), "", operative_text, count=1
        ).strip()

        all_chunks.extend(_chunk_section(doc_id, citation_num, title, operative_text))

    return _dedupe_chunk_ids(all_chunks)


def _dedupe_chunk_ids(chunks: list[dict]) -> list[dict]:
    """Citation-derived chunk_ids are readable but not guaranteed unique --
    found in practice on njac_5_23.pdf (the full UCC, all 12 subchapters):
    nested numbered lists within the same lettered subsection can restart at
    "1." (e.g. a sub-list inside item 3 also starting at 1), producing two
    numbered-item groups that both resolve to the same "(a).1+" citation.
    SQLite's UNIQUE constraint on chunk_id correctly caught this rather than
    silently overwriting a chunk. Guarantee uniqueness by construction here
    instead of trusting citation text to never collide."""
    seen: dict[str, int] = {}
    for chunk in chunks:
        cid = chunk["chunk_id"]
        if cid in seen:
            seen[cid] += 1
            chunk["chunk_id"] = f"{cid}#{seen[cid]}"
        else:
            seen[cid] = 1
    return chunks

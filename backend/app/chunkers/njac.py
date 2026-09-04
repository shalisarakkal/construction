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

from .generic import split_sentences

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
HISTORY_LABEL_RE = re.compile(r"^HISTORY:\s*\n?", re.IGNORECASE)
# Trailing "Annotations / Notes / Chapter Notes / NEW JERSEY ADMINISTRATIVE
# CODE / Copyright ..." boilerplate (sometimes with real case-law commentary
# mixed in under "Case Notes") appears at the end of every real section in
# this corpus (verified: present in all 291) -- previously silently included
# in operative_text whenever a section had no History block to split it off
# first (found live in 22 already-ingested chunks, e.g. N.J.A.C. 5:23-1.2).
# Stripped from both operative_text and the History chunk below.
ANNOTATIONS_FOOTER_RE = re.compile(r"\n\s*Annotations\s*\n.*", re.DOTALL)
CROSSREF_RE = re.compile(rf"N\.J\.A\.C\.\s*{SUBCHAPTER_NUM_RE}(?:\([a-z0-9]+\))*")
STANDARD_REF_RE = re.compile(r"ASME\s+A1[0-9]\.\d(?:-\d{4})?|ICC\s+A117\.1")

MAX_CHUNK_WORDS = 500

# A numbered item below this is treated as too small/context-free to embed
# usefully alone (e.g. "Addition of rope equalizers") and gets merged with
# its neighbors. At or above it, an item is normally already a complete,
# independently-citable provision -- merging it further risks diluting its
# embedding with unrelated neighboring items and hurting retrieval for
# anything specific to it. Found empirically: a fence-permit-exemption item
# (~30 words) bundled into one 472-word chunk with four unrelated permit
# exemptions (gas metering, signs, sheds, lead abatement) scored too low to
# make the top results for an on-topic fence question -- see
# docs/AllDevFlow.md's "chunking dilution" finding, 2026-09-04.
MIN_GROUP_WORDS = 20

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


def _make_chunk(doc_id: str, citation: str, section_title: str, text: str,
                 chunk_type: str = "njac_section") -> dict:
    return {
        "chunk_id": f"{doc_id}__{citation.replace('N.J.A.C. ', '')}",
        "doc_id": doc_id,
        "chunk_type": chunk_type,
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
    pieces = []
    if idxs[0] > 0:
        # Text before the first match (e.g. "(b) The following are exceptions
        # from (a) above:" ahead of numbered item "1.") used to be silently
        # dropped here -- confirmed real content loss against the live corpus
        # (njac_5_23_2.pdf's actual 5:23-2.14(b) intro sentence was missing
        # from the ingested chunk). Keep it as a leading piece instead; the
        # caller merges it into its first real item group rather than losing
        # it. See docs/AllDevFlow.md, 2026-09-04.
        pieces.append(text[: idxs[0]].strip())
    idxs.append(len(text))
    pieces.extend(text[idxs[i]: idxs[i + 1]].strip() for i in range(len(idxs) - 1))
    return pieces


def _split_oversized_text(doc_id: str, title: str, header: str, citation: str, text: str) -> list[dict]:
    """Last-resort split for a piece of text that's still oversized after
    exhausting lettered/numbered structure -- no further reliable
    structural marker to split on (e.g. a numbered item with a deep nested
    romanette/lettered sub-list but no clean top-level break, or an
    oversized lettered piece / intro block with no numbered items at all).
    Falls back to sentence-level grouping, same approach as
    _chunk_history_text uses for oversized History blocks -- the level-4
    fallback NJ/eval/chunking_strategy.md originally sketched ("fall back
    to sentence-level splitting... if that item alone exceeds ~400 words")
    but was never actually implemented. Found live: 36 chunks up to 2,803
    words (e.g. N.J.A.C. 5:23-3.14(b).31) -- see docs/AllDevFlow.md,
    2026-09-04."""
    base_citation = f"N.J.A.C. {citation}"
    header_budget = len(f"{header} {citation} (99)".split())
    effective_cap = MAX_CHUNK_WORDS - header_budget

    sentences = split_sentences(text)
    chunks = []
    group: list[str] = []
    group_words = 0
    part = 1

    def flush():
        nonlocal group, group_words, part
        if not group:
            return
        part_citation = f"{base_citation} ({part})"
        part_text = f"{header} {citation} ({part})\n" + " ".join(group)
        chunks.append(_make_chunk(doc_id, part_citation, title, part_text))
        part += 1
        group = []
        group_words = 0

    for sentence in sentences:
        words = len(sentence.split())
        if group_words + words > effective_cap and group:
            flush()
        group.append(sentence)
        group_words += words
    flush()
    return chunks


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
        # No numbered items to split on further -- fall back to
        # sentence-level grouping rather than one oversized chunk.
        return _split_oversized_text(doc_id, title, header, sub_citation, piece)

    chunks = []
    group: list[str] = []
    group_words = 0

    def flush():
        nonlocal group, group_words
        if not group:
            return
        # A group can start with intro text ahead of the first numbered item
        # (see _split_on's leading-piece handling above) -- scan the whole
        # group for the first real numbered item rather than assuming
        # group[0] is one, so that intro text doesn't produce a "?" citation.
        start_num = "?"
        for member in group:
            num_match = re.match(r"^(\d+)\.", member)
            if num_match:
                start_num = num_match.group(1)
                break
        item_citation = f"{sub_citation}.{start_num}" if len(group) == 1 else f"{sub_citation}.{start_num}+"
        text = f"{header} {item_citation}\n" + "\n".join(group)
        if len(group) == 1 and len(text.split()) > MAX_CHUNK_WORDS:
            # A single item (or a single oversized intro block with no
            # numbered item of its own -- the "?" citation case) that's
            # still too big on its own -- no lettered/numbered structure
            # left to split on, fall back to sentence-level grouping.
            chunks.extend(_split_oversized_text(doc_id, title, header, item_citation, group[0]))
        else:
            chunks.append(_make_chunk(doc_id, f"N.J.A.C. {item_citation}", title, text))
        group = []
        group_words = 0

    for item in numbered_pieces:
        words = len(item.split())
        # Close the current group before adding this item if it's already
        # substantial enough to stand alone (MIN_GROUP_WORDS) or would
        # overflow the hard cap -- either way, don't dilute it further.
        if group and (group_words >= MIN_GROUP_WORDS or group_words + words > MAX_CHUNK_WORDS):
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


def _chunk_history_text(doc_id: str, citation_num: str, title: str, history_text: str) -> list[dict]:
    """The HISTORY: block (amendment log) was previously discarded entirely
    -- see docs/AllDevFlow.md's eval-set finding: a question like "when was
    this amended" has a real answer in the source PDF that was never
    indexed. Indexed here as its own low-priority chunk (chunk_type
    "njac_history"), separate from operative_text, so it's retrievable
    without polluting the regulatory-text embeddings.

    Most sections' history is short (median 114 words across this corpus)
    and fits in one chunk, but heavily-amended sections can be much larger
    (up to ~1,900 words) -- unlike operative_text there's no lettered/
    numbered structure to split on, so oversized history is split the same
    way the generic chunker splits prose: group sentences up to
    MAX_CHUNK_WORDS. Grouping unrelated-topic items was the bug fixed for
    numbered items (MIN_GROUP_WORDS above) -- that doesn't apply here, since
    consecutive amendment entries are all the same topic (this section's
    history), so grouping them densely doesn't dilute anything."""
    base_citation = f"N.J.A.C. {citation_num} History"
    header = f"N.J.A.C. {citation_num} — {title} — Amendment History"
    full_text = f"{header}\n{history_text}"

    if len(full_text.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, base_citation, title, full_text, chunk_type="njac_history")]

    # Reserve room for the "{header} ({part})" prefix so the *final* chunk
    # text (header included) respects MAX_CHUNK_WORDS, not just the sentence
    # group -- word_count is measured on the full chunk text below.
    header_budget = len(f"{header} (99)".split())
    effective_cap = MAX_CHUNK_WORDS - header_budget

    sentences = split_sentences(history_text)
    chunks = []
    group: list[str] = []
    group_words = 0
    part = 1

    def flush():
        nonlocal group, group_words, part
        if not group:
            return
        citation = f"{base_citation} ({part})"
        text = f"{header} ({part})\n" + " ".join(group)
        chunks.append(_make_chunk(doc_id, citation, title, text, chunk_type="njac_history"))
        part += 1
        group = []
        group_words = 0

    for sentence in sentences:
        words = len(sentence.split())
        if group_words + words > effective_cap and group:
            flush()
        group.append(sentence)
        group_words += words
    flush()
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
        # Defensive: the Annotations/copyright footer only ever trails after
        # History, so it's only actually present in operative_text when a
        # section has no History block to split it off (parts has length 1)
        # -- but strip unconditionally rather than special-casing that.
        operative_text = ANNOTATIONS_FOOTER_RE.sub("", operative_text).strip()

        all_chunks.extend(_chunk_section(doc_id, citation_num, title, operative_text))

        if len(parts) > 1:
            history_text = ANNOTATIONS_FOOTER_RE.sub("", parts[1]).strip()
            history_text = HISTORY_LABEL_RE.sub("", history_text).strip()
            if history_text:
                all_chunks.extend(_chunk_history_text(doc_id, citation_num, title, history_text))

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

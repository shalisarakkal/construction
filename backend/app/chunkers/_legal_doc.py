"""Shared, format-parameterized chunking engine behind both njac.py (NJAC
regulations) and statute.py (LexisNexis-exported NJ statutes). Split out once
a genuine second consumer appeared -- see docs/AllDevFlow.md, 2026-09-04:
52_27D_119.pdf turned out to have the exact same per-section structure as
the NJAC exports (repeated page boilerplate, "History", "Annotations",
"End of Document"), just with different citation/subsection delimiter
conventions ("a." + "(1)" instead of "(a)" + "1."). Rather than duplicate
~250 lines of recursive lettered/numbered splitting, oversized-chunk
fallback, and History handling, both format modules configure this engine
via LegalDocConfig and provide only their own regexes/detection/constants.

Recursive split order when a section is too large:
  1. whole section (if <= MAX_CHUNK_WORDS)
  2. split on lettered subsections
  3. split an oversized lettered subsection further on numbered items
  4. split an oversized single item (or a lettered piece with no numbered
     items at all) at the sentence level -- no more structure to rely on
"""

from dataclasses import dataclass
import re

from .generic import split_sentences

END_OF_DOC_RE = re.compile(r"\bEnd of Document\b")
HISTORY_SPLIT_RE = re.compile(r"\n\s*History\s*\n", re.IGNORECASE)
HISTORY_LABEL_RE = re.compile(r"^HISTORY:\s*\n?", re.IGNORECASE)
# Trailing "Annotations" content (case-law digests, cross-references, and
# assorted "Notes / Chapter Notes / copyright" boilerplate) is dropped
# entirely rather than indexed -- for NJAC sections it's mostly boilerplate
# with occasional case commentary; for statute sections it's the bulk of
# each section's page count and is fundamentally different content (case
# law about the statute, not the statute itself). Confirmed both formats
# consistently use this literal heading. See docs/AllDevFlow.md, 2026-09-04.
ANNOTATIONS_FOOTER_RE = re.compile(r"\n\s*Annotations\s*\n.*", re.DOTALL)

MAX_CHUNK_WORDS = 500

# A numbered item below this is treated as too small/context-free to embed
# usefully alone (e.g. "Addition of rope equalizers") and gets merged with
# its neighbors. At or above it, an item is normally already a complete,
# independently-citable provision -- merging it further risks diluting its
# embedding with unrelated neighboring items and hurting retrieval for
# anything specific to it. Found empirically in njac_5_23_2.pdf -- see
# docs/AllDevFlow.md's "chunking dilution" finding, 2026-09-04.
MIN_GROUP_WORDS = 20


@dataclass(frozen=True)
class LegalDocConfig:
    citation_prefix: str  # e.g. "N.J.A.C." or "N.J. Stat. §"
    section_chunk_type: str  # e.g. "njac_section" / "statute_section"
    history_chunk_type: str  # e.g. "njac_history" / "statute_history"
    section_heading_re: re.Pattern  # 2 groups: citation_num, title
    lettered_sub_re: re.Pattern  # 1 group: the letter, matches at line start
    numbered_sub_re: re.Pattern  # 1 group: the number, matches at line start
    page_boilerplate_patterns: list[re.Pattern]
    cross_ref_res: list[re.Pattern]


def _extract_references(text: str, cfg: LegalDocConfig) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    refs: set[str] = set()
    for pattern in cfg.cross_ref_res:
        refs.update(pattern.findall(flat))
    return sorted(refs)


def _make_chunk(doc_id: str, citation: str, section_title: str, text: str,
                 cfg: LegalDocConfig, chunk_type: str | None = None) -> dict:
    return {
        "chunk_id": f"{doc_id}__{citation.replace(f'{cfg.citation_prefix} ', '')}",
        "doc_id": doc_id,
        "chunk_type": chunk_type or cfg.section_chunk_type,
        "citation": citation,
        "section_title": section_title,
        "page_number": None,
        "text": text,
        "word_count": len(text.split()),
        "references": _extract_references(text, cfg),
    }


def _split_into_raw_sections(full_text: str) -> list[str]:
    pieces = END_OF_DOC_RE.split(full_text)
    return [p.strip() for p in pieces if p.strip()]


def _strip_page_boilerplate(raw_section: str, cfg: LegalDocConfig) -> str:
    text = raw_section
    for pattern in cfg.page_boilerplate_patterns:
        text = pattern.sub("", text)
    return text


def _heading_pattern(citation_num: str, title: str) -> re.Pattern:
    """Matches the "§ CITATION[.] TITLE" heading line. The period after the
    citation number is optional: present in statute exports ("§ 52:27D-121.
    Definitions"), absent in NJAC exports ("§ 5:23-12.5 Registration fee").
    Found live: using a literal (period-less) string here silently no-opped
    every heading-dedupe/strip call against statute text -- see
    docs/AllDevFlow.md, 2026-09-04."""
    return re.compile(rf"§\s*{re.escape(citation_num)}\.?\s+{re.escape(title)}")


def _dedupe_repeated_heading(text: str, citation_num: str, title: str) -> str:
    pattern = _heading_pattern(citation_num, title)
    match = pattern.search(text)
    if match is None:
        return text
    before = text[: match.end()]
    after = pattern.sub("", text[match.end():])
    return before + after


def _split_on(regex: re.Pattern, text: str) -> list[str]:
    idxs = [m.start() for m in regex.finditer(text)]
    if not idxs:
        return [text]
    pieces = []
    if idxs[0] > 0:
        # Text before the first match (e.g. intro text ahead of the first
        # numbered item) used to be silently dropped here -- confirmed real
        # content loss on the live corpus. Kept as a leading piece instead;
        # the caller merges it into its first real item group rather than
        # losing it. See docs/AllDevFlow.md, 2026-09-04.
        pieces.append(text[: idxs[0]].strip())
    idxs.append(len(text))
    pieces.extend(text[idxs[i]: idxs[i + 1]].strip() for i in range(len(idxs) - 1))
    return pieces


def _split_oversized_text(doc_id: str, title: str, header: str, citation: str, text: str,
                           cfg: LegalDocConfig, chunk_type: str | None = None) -> list[dict]:
    """Last-resort split for a piece of text that's still oversized after
    exhausting lettered/numbered structure. Falls back to sentence-level
    grouping, same approach _chunk_history_text uses for oversized History
    blocks -- the level-4 fallback originally sketched at design time
    ("fall back to sentence-level splitting... if that item alone exceeds
    ~400 words") but never actually implemented. See docs/AllDevFlow.md,
    2026-09-04."""
    base_citation = f"{cfg.citation_prefix} {citation}"
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
        chunks.append(_make_chunk(doc_id, part_citation, title, part_text, cfg, chunk_type))
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


def _chunk_lettered_piece(doc_id: str, citation_num: str, title: str, header: str, piece: str,
                           cfg: LegalDocConfig) -> list[dict]:
    """piece is one lettered subsection block (or the whole section if no
    lettered markers were found). Split further on numbered items if still
    too large."""
    letter_match = cfg.lettered_sub_re.match(piece)
    letter = letter_match.group(1) if letter_match else "intro"
    sub_citation = f"{citation_num}({letter})" if letter_match else citation_num
    prefixed = f"{header} {sub_citation}\n{piece}"

    if len(prefixed.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, f"{cfg.citation_prefix} {sub_citation}", title, prefixed, cfg)]

    # level 3: split on numbered items, regrouping consecutive short ones
    # up to MAX_CHUNK_WORDS instead of one chunk per item
    numbered_pieces = _split_on(cfg.numbered_sub_re, piece)
    if len(numbered_pieces) <= 1:
        # No numbered items to split on further -- fall back to
        # sentence-level grouping rather than one oversized chunk.
        return _split_oversized_text(doc_id, title, header, sub_citation, piece, cfg)

    chunks = []
    group: list[str] = []
    group_words = 0

    def flush():
        nonlocal group, group_words
        if not group:
            return
        # A group can start with intro text ahead of the first numbered item
        # -- scan the whole group for the first real numbered item rather
        # than assuming group[0] is one, so that intro text doesn't produce
        # a "?" citation.
        start_num = "?"
        for member in group:
            num_match = cfg.numbered_sub_re.match(member)
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
            chunks.extend(_split_oversized_text(doc_id, title, header, item_citation, group[0], cfg))
        else:
            chunks.append(_make_chunk(doc_id, f"{cfg.citation_prefix} {item_citation}", title, text, cfg))
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


def _chunk_section(doc_id: str, citation_num: str, title: str, operative_text: str,
                    cfg: LegalDocConfig) -> list[dict]:
    header = f"{cfg.citation_prefix} {citation_num} — {title}"
    full_with_header = f"{header}\n{operative_text}"

    if len(full_with_header.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, f"{cfg.citation_prefix} {citation_num}", title, full_with_header, cfg)]

    chunks = []
    for piece in _split_on(cfg.lettered_sub_re, operative_text):
        chunks.extend(_chunk_lettered_piece(doc_id, citation_num, title, header, piece, cfg))
    return chunks


def _chunk_history_text(doc_id: str, citation_num: str, title: str, history_text: str,
                         cfg: LegalDocConfig) -> list[dict]:
    """The HISTORY: block (amendment/enactment log) was previously discarded
    entirely -- see docs/AllDevFlow.md's eval-set finding: a question like
    "when was this amended" has a real answer in the source PDF that was
    never indexed. Indexed here as its own chunk, separate from
    operative_text, so it's retrievable without polluting the regulatory-
    text embeddings.

    Unlike operative_text there's no lettered/numbered structure to split
    on, so oversized history is split the way the generic chunker splits
    prose: group sentences up to MAX_CHUNK_WORDS. MIN_GROUP_WORDS
    deliberately does not apply here: it exists to stop grouping
    *topically unrelated* items together, but consecutive amendment
    entries for the same section are all the same topic, so grouping them
    densely doesn't dilute anything."""
    base_citation = f"{cfg.citation_prefix} {citation_num} History"
    header = f"{cfg.citation_prefix} {citation_num} — {title} — Amendment History"
    full_text = f"{header}\n{history_text}"

    if len(full_text.split()) <= MAX_CHUNK_WORDS:
        return [_make_chunk(doc_id, base_citation, title, full_text, cfg, cfg.history_chunk_type)]

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
        chunks.append(_make_chunk(doc_id, citation, title, text, cfg, cfg.history_chunk_type))
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


def chunk_legal_document(doc_id: str, full_text: str, cfg: LegalDocConfig) -> list[dict]:
    raw_sections = _split_into_raw_sections(full_text)
    all_chunks: list[dict] = []

    for raw in raw_sections:
        m = cfg.section_heading_re.search(raw)
        if not m:
            continue
        citation_num, title = m.group(1), m.group(2).strip()

        cleaned = _strip_page_boilerplate(raw, cfg)
        cleaned = _dedupe_repeated_heading(cleaned, citation_num, title)

        parts = HISTORY_SPLIT_RE.split(cleaned, maxsplit=1)
        operative_text = parts[0].strip()
        operative_text = _heading_pattern(citation_num, title).sub("", operative_text, count=1).strip()
        # Defensive: the Annotations footer only ever trails after History,
        # so it's only actually present in operative_text when a section
        # has no History block to split it off (parts has length 1) -- but
        # strip unconditionally rather than special-casing that.
        operative_text = ANNOTATIONS_FOOTER_RE.sub("", operative_text).strip()

        all_chunks.extend(_chunk_section(doc_id, citation_num, title, operative_text, cfg))

        if len(parts) > 1:
            history_text = ANNOTATIONS_FOOTER_RE.sub("", parts[1]).strip()
            history_text = HISTORY_LABEL_RE.sub("", history_text).strip()
            if history_text:
                all_chunks.extend(_chunk_history_text(doc_id, citation_num, title, history_text, cfg))

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

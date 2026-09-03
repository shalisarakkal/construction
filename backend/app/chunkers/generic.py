"""Fallback chunker for engineering documents that aren't NJAC regulations:
plain PDFs, CAD/GIS export notes, etc. Implements the original dream.md plan
(section 2): split into sentences, greedily group into ~300-400 word chunks,
independently per page.

Sentence splitting uses a regex heuristic rather than NLTK/spaCy to avoid a
runtime model download dependency for Phase 1. It's good enough for
paragraph-style engineering prose; swap in spaCy if sentence quality on real
documents turns out to matter (tracked in docs/AllDevFlow.md backlog).
"""

import re

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
TARGET_MIN_WORDS = 250
TARGET_MAX_WORDS = 400


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def chunk_page(doc_id: str, page_number: int, page_text: str, start_index: int):
    """Greedily group sentences into ~300-400 word chunks. Returns
    (chunks, next_index)."""
    sentences = split_sentences(page_text)
    chunks = []
    current: list[str] = []
    current_words = 0
    idx = start_index

    def flush():
        nonlocal current, current_words, idx
        if not current:
            return
        text = " ".join(current)
        chunks.append({
            "chunk_id": f"{doc_id}_{idx}",
            "doc_id": doc_id,
            "chunk_type": "generic",
            "citation": None,
            "section_title": None,
            "page_number": page_number,
            "text": text,
            "word_count": len(text.split()),
            "references": [],
        })
        idx += 1
        current = []
        current_words = 0

    for sentence in sentences:
        words = len(sentence.split())
        if current_words + words > TARGET_MAX_WORDS and current_words >= TARGET_MIN_WORDS:
            flush()
        current.append(sentence)
        current_words += words
        if current_words >= TARGET_MAX_WORDS:
            flush()

    flush()
    return chunks, idx


def generic_chunk(doc_id: str, pages: list[str]) -> list[dict]:
    """pages: list of extracted page texts, in order (page_number = index+1)."""
    all_chunks = []
    next_index = 0
    for page_number, page_text in enumerate(pages, start=1):
        page_chunks, next_index = chunk_page(doc_id, page_number, page_text, next_index)
        all_chunks.extend(page_chunks)
    return all_chunks

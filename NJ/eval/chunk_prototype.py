"""
Prototype structure-aware chunker for NJAC regulation PDFs, sketched against
NJ/pdfs/njac_5_23_12.pdf. Not wired into a pipeline yet -- this is Phase 0
scaffolding to validate the chunking strategy in chunking_strategy.md before
Phase 1 builds the real ingestion service.

Requires: pip install pdfplumber
Run:      python chunk_prototype.py ../pdfs/njac_5_23_12.pdf

NOTE ON A REAL GOTCHA FOUND WHILE BUILDING THIS:
These exported NJAC PDFs re-print a boilerplate header block (the bare
"N.J.A.C. 5:23-12.X" citation line, the "This file includes all Regulations
..." register-vintage line, the breadcrumb, and even the "§ 5:23-12.X Title"
heading itself) at the TOP OF EVERY PAGE, not just the first page of a
section. Splitting naively on "§ 5:23-12.X Title" therefore fragments one
section into N pieces (one per PDF page it spans) instead of finding true
section boundaries. The one marker that reliably appears exactly once per
real section is "End of Document" -- so we segment on that first, then strip
repeated per-page boilerplate out of each segment before applying the
lettered-subsection recursive split.
"""

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pdfplumber

END_OF_DOC_RE = re.compile(r"\bEnd of Document\b")
SECTION_HEADING_RE = re.compile(r"^§\s*(5:23-\d+(?:\.\d+)?)\s+(.+)$", re.MULTILINE)
LETTERED_SUB_RE = re.compile(r"(?m)^\(([a-z])\)\s")
HISTORY_SPLIT_RE = re.compile(r"\n\s*History\s*\n", re.IGNORECASE)
CROSSREF_RE = re.compile(r"N\.J\.A\.C\.\s*5:23-\d+(?:\.\d+)?(?:\([a-z0-9]+\))*")
STANDARD_REF_RE = re.compile(r"ASME\s+A1[0-9]\.\d(?:-\d{4})?|ICC\s+A117\.1")
MAX_CHUNK_WORDS = 500

# Per-page boilerplate that repeats inside a single section's page range.
# Order matters: strip the wrapped multi-line blocks before the single-line ones.
PAGE_BOILERPLATE_PATTERNS = [
    re.compile(r"This file includes all Regulations adopted and published through the New Jersey Register,\s*Vol\.\s*\d+\s*No\.\s*\d+,\s*\n.*?\d{4}\n", re.DOTALL),
    re.compile(r"NJ - New Jersey Administrative Code\s*>\s*TITLE 5\. COMMUNITY AFFAIRS\s*>\s*CHAPTER 23\. UNIFORM\s*\nCONSTRUCTION CODE\s*>\s*SUBCHAPTER 12\. ELEVATOR SAFETY SUBCODE\n?"),
    re.compile(r"^N\.J\.A\.C\.\s*5:23-\d+(?:\.\d+)?\s*$", re.MULTILINE),
    re.compile(r"^Page \d+ of \d+\s*$", re.MULTILINE),
]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    citation: str
    section_title: str
    chunk_type: str
    text: str
    word_count: int = field(init=False)
    references: list = field(default_factory=list)

    def __post_init__(self):
        self.word_count = len(self.text.split())
        flat = re.sub(r"\s+", " ", self.text)
        refs = set(CROSSREF_RE.findall(flat)) | set(STANDARD_REF_RE.findall(flat))
        self.references = sorted(refs)


def extract_full_text(pdf_path: Path) -> str:
    """Pull the text layer page by page. These NJ-hosted regulation PDFs have
    a clean native text layer -- no OCR needed."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def split_into_raw_sections(full_text: str):
    """True section boundary = 'End of Document', which appears exactly once
    per section regardless of how many pages it spans."""
    pieces = END_OF_DOC_RE.split(full_text)
    return [p.strip() for p in pieces if p.strip()]


def strip_page_boilerplate(raw_section: str) -> str:
    text = raw_section
    for pattern in PAGE_BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    return text


def dedupe_repeated_heading(text: str, citation_num: str, title: str) -> str:
    """The '§ 5:23-12.X Title' heading line repeats once per page within the
    section; keep only the first occurrence."""
    heading_line = f"§ {citation_num} {title}"
    first_idx = text.find(heading_line)
    if first_idx == -1:
        return text
    before = text[:first_idx + len(heading_line)]
    after = text[first_idx + len(heading_line):]
    after = after.replace(heading_line, "")
    return before + after


def split_on_lettered_subsections(text: str):
    idxs = [m.start() for m in LETTERED_SUB_RE.finditer(text)]
    if not idxs:
        return [text]
    idxs.append(len(text))
    return [text[idxs[i]:idxs[i + 1]].strip() for i in range(len(idxs) - 1)]


def chunk_section(doc_id: str, citation_num: str, title: str, operative_text: str):
    header = f"N.J.A.C. {citation_num} — {title}"
    full_with_header = f"{header}\n{operative_text}"

    if len(full_with_header.split()) <= MAX_CHUNK_WORDS:
        return [Chunk(
            chunk_id=f"{doc_id}__{citation_num}",
            doc_id=doc_id,
            citation=f"N.J.A.C. {citation_num}",
            section_title=title,
            chunk_type="body",
            text=full_with_header,
        )]

    chunks = []
    for sub in split_on_lettered_subsections(operative_text):
        letter_match = re.match(r"^\(([a-z])\)", sub)
        letter = letter_match.group(1) if letter_match else "intro"
        sub_citation = f"{citation_num}({letter})" if letter_match else citation_num
        prefixed = f"{header} {sub_citation}\n{sub}"
        chunks.append(Chunk(
            chunk_id=f"{doc_id}__{citation_num}_{letter}",
            doc_id=doc_id,
            citation=f"N.J.A.C. {sub_citation}",
            section_title=title,
            chunk_type="body",
            text=prefixed,
        ))
    return chunks


def main():
    if len(sys.argv) != 2:
        print("usage: python chunk_prototype.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    doc_id = pdf_path.stem

    full_text = extract_full_text(pdf_path)
    raw_sections = split_into_raw_sections(full_text)

    all_chunks = []
    histories = {}
    skipped = []

    for raw in raw_sections:
        m = SECTION_HEADING_RE.search(raw)
        if not m:
            skipped.append(raw[:80])
            continue
        citation_num, title = m.group(1), m.group(2).strip()

        cleaned = strip_page_boilerplate(raw)
        cleaned = dedupe_repeated_heading(cleaned, citation_num, title)

        parts = HISTORY_SPLIT_RE.split(cleaned, maxsplit=1)
        operative_text = parts[0].strip()
        # drop the leading "§ 5:23-12.X Title" heading line itself from the body
        operative_text = re.sub(re.escape(f"§ {citation_num} {title}"), "", operative_text, count=1).strip()
        amendment_history = parts[1].strip() if len(parts) > 1 else ""
        histories[citation_num] = amendment_history

        all_chunks.extend(chunk_section(doc_id, citation_num, title, operative_text))

    out_dir = pdf_path.parent.parent / "eval" / "chunk_output"
    out_dir.mkdir(exist_ok=True)

    chunks_path = out_dir / f"{doc_id}.chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in all_chunks], f, indent=2)

    history_path = out_dir / f"{doc_id}.history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(histories, f, indent=2)

    print(f"Raw 'End of Document' segments: {len(raw_sections)}")
    print(f"Segments skipped (no § heading found): {len(skipped)}")
    for s in skipped:
        print(f"  SKIPPED: {s!r}")
    print(f"True sections recognized: {len(histories)}")
    print(f"Chunks produced: {len(all_chunks)}")
    print(f"Wrote {chunks_path}")
    print(f"Wrote {history_path}")

    print("\nWord-count distribution per chunk:")
    for c in all_chunks:
        print(f"  {c.chunk_id:45s} {c.word_count:4d} words  refs={c.references}")


if __name__ == "__main__":
    main()

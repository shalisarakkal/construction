"""Standalone chunker test — no FastAPI/embeddings/FAISS needed. Extracts
text from a real PDF and runs it through the njac/generic chunker directly,
so chunking logic can be iterated on without booting the whole service.

Run: backend\\.venv\\Scripts\\python.exe backend\\tests\\test_chunking.py <path-to-pdf>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from app.chunkers import generic_chunk, looks_like_njac, njac_chunk


def extract_pages(pdf_path: Path) -> list[str]:
    with pdfplumber.open(pdf_path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def main():
    if len(sys.argv) != 2:
        print("usage: test_chunking.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    doc_id = pdf_path.stem
    pages = extract_pages(pdf_path)
    full_text = "\n".join(pages)

    if looks_like_njac(full_text):
        chunker_used = "njac"
        chunks = njac_chunk(doc_id, full_text)
    else:
        chunker_used = "generic"
        chunks = generic_chunk(doc_id, pages)

    print(f"Document: {pdf_path.name}")
    print(f"Pages: {len(pages)}")
    print(f"Chunker selected: {chunker_used}")
    print(f"Chunks produced: {len(chunks)}\n")

    print(f"{'chunk_id':45s} {'words':>6s}  citation")
    print("-" * 90)
    for c in chunks:
        citation = c.get("citation") or f"page {c.get('page_number')}"
        print(f"{c['chunk_id']:45s} {c['word_count']:6d}  {citation}")

    over_limit = [c for c in chunks if c["word_count"] > 500]
    print(f"\nChunks over 500 words: {len(over_limit)}")
    for c in over_limit:
        print(f"  {c['chunk_id']} -> {c['word_count']} words")

    out_path = pdf_path.parent.parent / "eval" / "chunk_output" / f"{doc_id}.backend_chunks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    print(f"\nWrote full chunk output to {out_path}")

    print("\nSample chunk (first):")
    print(json.dumps(chunks[0], indent=2)[:800])


if __name__ == "__main__":
    main()

"""Format-specific text extraction, one function per supported file type.
Split out from ingestion.py so the orchestration logic (ingestion.py) stays
about "what to do with extracted pages," not "how to extract them" -- mirrors
the pluggable-chunker-registry pattern in app/chunkers/.

Phase 1 supported PDF only. Phase 2 adds DOCX/TXT (dream.md section 1.2:
"CAD/GIS notes -> text: Treat exported PDF/TXT/DOCX as standard documents")
and OCR fallback for scanned PDFs (see app/ocr.py).
"""

from pathlib import Path

import pdfplumber

from . import ocr

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def extract_pdf_pages(pdf_path: Path) -> tuple[list[str], str]:
    """Returns (pages, ocr_status). ocr_status is one of:
    "not_needed" (every page had a text layer), "used" (OCR filled in at
    least one page), "unavailable" (a page needed OCR but Tesseract isn't
    installed -- pages are left empty, caller decides how to report this)."""
    with pdfplumber.open(pdf_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]

    needs_ocr = [i for i, text in enumerate(pages) if ocr.page_needs_ocr(text)]
    if not needs_ocr:
        return pages, "not_needed"

    if not ocr.is_available():
        return pages, "unavailable"

    ocr_results = ocr.ocr_pdf_pages(pdf_path, needs_ocr)
    for i, text in ocr_results.items():
        pages[i] = text
    return pages, "used"


def extract_docx_pages(docx_path: Path) -> list[str]:
    """python-docx has no reliable page-break API, so the whole document is
    treated as a single page -- page_number metadata will be None for DOCX
    chunks via the generic chunker. Acceptable for Phase 2: DOCX sources so
    far are addenda/notes, not the multi-hundred-page regulation PDFs where
    page numbers matter for citation."""
    import docx

    document = docx.Document(docx_path)
    text = "\n".join(p.text for p in document.paragraphs)
    return [text]


def extract_txt_pages(txt_path: Path) -> list[str]:
    return [txt_path.read_text(encoding="utf-8", errors="replace")]

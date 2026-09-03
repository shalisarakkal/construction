"""Optional OCR fallback for scanned/image-only PDF pages -- dream.md
section 1.2: "Images -> OCR: Use Tesseract or Azure Vision OCR."

Tesseract chosen over a cloud OCR API for the same reason local embeddings
were chosen over an API in Phase 1 (see docs/AllDevFlow.md): no per-page
cost, no network dependency, consistent with the project's local-first
default. Tesseract itself is a system binary, not pip-installable, so
is_available() is checked at ingest time and a clear error is raised (not a
silent skip) when a scanned PDF is uploaded but Tesseract isn't installed --
see the 4 real scanned NJAC subchapter files that surfaced this need
(njac_5_23_3A/4A/4B_C/4D.pdf, all "no extractable text" during Phase 1).

Pages are rasterized with PyMuPDF (pure pip wheel, no external binary needed
for rendering) and OCR'd individually with pytesseract, rather than OCRing
every page of every PDF -- only pages pdfplumber found near-empty are
rasterized, so a mostly-text document with one scanned page pays OCR cost
for just that page.
"""

import shutil
from functools import lru_cache
from pathlib import Path

MIN_TEXT_CHARS = 20  # below this, a page is treated as "no extractable text"
OCR_DPI = 300  # standard OCR-quality resolution; higher costs more time

# Windows installers update the system/user PATH registry keys, but a
# process already running (or spawned from a shell started before the
# install) won't see that update until a fresh login/session -- so PATH
# alone isn't reliable right after installing Tesseract. Fall back to the
# UB-Mannheim installer's default location rather than requiring a restart.
_DEFAULT_WINDOWS_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def page_needs_ocr(text: str) -> bool:
    return len((text or "").strip()) < MIN_TEXT_CHARS


@lru_cache
def is_available() -> bool:
    try:
        import pytesseract

        if shutil.which("tesseract") is None and _DEFAULT_WINDOWS_PATH.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_DEFAULT_WINDOWS_PATH)

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_pdf_pages(pdf_path: Path, page_indices: list[int]) -> dict[int, str]:
    """OCRs only the given 0-indexed pages, returns {page_index: text}."""
    import io

    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image

    results: dict[int, str] = {}
    zoom = OCR_DPI / 72
    doc = fitz.open(pdf_path)
    try:
        for i in page_indices:
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            results[i] = pytesseract.image_to_string(img)
    finally:
        doc.close()
    return results

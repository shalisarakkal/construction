"""Ties together extraction -> chunker selection -> embedding -> storage.

ingest_document() is the slow part (PDF parsing + embedding can take seconds
to minutes per document) and runs inside a FastAPI BackgroundTask kicked off
by routers/upload.py, not inline in the request handler -- see that router
and vector_store.py's jobs table for the job-status polling this enables."""

import hashlib
import shutil
import uuid
from pathlib import Path

from . import vector_store
from .chunkers import generic_chunk, looks_like_njac, njac_chunk
from .config import settings
from .embeddings import embed_texts
from .extractors import extract_docx_pages, extract_pdf_pages, extract_txt_pages


class DuplicateDocumentError(ValueError):
    """Raised when the uploaded file's content exactly matches an
    already-ingested document -- see docs/AllDevFlow.md Phase 2 notes.
    Carries the existing document's info so the caller can report it."""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__(
            f"This file was already ingested as '{existing['title']}' (doc_id={existing['doc_id']})"
        )


def validate_upload(file_bytes: bytes, supersedes_doc_id: str | None = None) -> str:
    """Fast synchronous prechecks (duplicate-hash + supersedes-target
    validation) that don't require the slow extract/chunk/embed pipeline, so
    /upload can reject a bad request immediately with 409/422 instead of
    making the caller poll a job just to learn it failed validation. Returns
    the content hash so ingest_document doesn't have to hash the file twice."""
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = vector_store.find_document_by_hash(content_hash)
    if existing:
        raise DuplicateDocumentError(existing)

    if supersedes_doc_id:
        target = vector_store.get_document(supersedes_doc_id)
        if target is None:
            raise ValueError(f"Cannot replace: document {supersedes_doc_id} does not exist")
        if not target["is_latest"]:
            raise ValueError(
                f"Cannot replace {supersedes_doc_id}: it has already been superseded by a "
                "newer version. Replace the current latest version of this document instead."
            )

    return content_hash


def ingest_document(file_bytes: bytes, filename: str, title: str | None,
                     supersedes_doc_id: str | None = None) -> dict:
    content_hash = validate_upload(file_bytes, supersedes_doc_id)

    doc_id = uuid.uuid4().hex[:12]
    doc_dir = settings.documents_dir / doc_id / "raw"
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_path = doc_dir / filename
    file_path.write_bytes(file_bytes)

    ext = file_path.suffix.lower()
    ocr_status = "not_applicable"
    if ext == ".pdf":
        pages, ocr_status = extract_pdf_pages(file_path)
    elif ext == ".docx":
        pages = extract_docx_pages(file_path)
    elif ext == ".txt":
        pages = extract_txt_pages(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    full_text = "\n".join(pages)

    if looks_like_njac(full_text):
        chunker_used = "njac"
        chunks = njac_chunk(doc_id, full_text)
        if not chunks:
            # looks_like_njac() only sniffs for NJAC boilerplate phrases, not
            # a real "§ X.Y Title" heading -- a placeholder/reserved
            # subchapter (e.g. njac_5_23_4B_C.pdf: "SUBCHAPTERS 4B AND 4C.
            # (RESERVED)") passes the sniff but has no section to chunk on.
            # Fall back to the generic chunker rather than erroring on a
            # document that plainly has real, extractable text.
            chunker_used = "generic"
            chunks = generic_chunk(doc_id, pages)
    else:
        chunker_used = "generic"
        chunks = generic_chunk(doc_id, pages)

    if not chunks:
        if ocr_status == "unavailable":
            raise ValueError(
                "No extractable text found in PDF, and OCR is unavailable "
                "(Tesseract is not installed on this server). Install Tesseract "
                "OCR to enable scanned-PDF support -- see docs/AllDevFlow.md Phase 2."
            )
        suffix = ", even after OCR" if ocr_status == "used" else ""
        raise ValueError(f"No extractable text found in document{suffix}")

    vectors = embed_texts([c["text"] for c in chunks])

    resolved_title = title or filename
    vector_store.add_document(
        doc_id, resolved_title, filename, chunker_used, chunks, vectors, content_hash,
        supersedes_doc_id=supersedes_doc_id,
    )

    return {
        "doc_id": doc_id,
        "title": resolved_title,
        "filename": filename,
        "chunker_used": chunker_used,
        "chunk_count": len(chunks),
        "ocr_used": ocr_status == "used",
        "supersedes_doc_id": supersedes_doc_id,
    }


def delete_document(doc_id: str) -> bool:
    """Deletes a document's DB rows (see vector_store.delete_document for why
    the FAISS index itself is left alone) and its raw uploaded file on disk.
    Returns False if the doc_id didn't exist."""
    deleted = vector_store.delete_document(doc_id)
    if not deleted:
        return False

    doc_dir = settings.documents_dir / doc_id
    if doc_dir.exists():
        shutil.rmtree(doc_dir)
    return True

"""Combined FAISS vector index + SQLite metadata store, per dream.md section
3.2 (FAISS for vectors, SQLite/Postgres for metadata since FAISS itself has
no metadata storage).

FAISS row ids are assigned sequentially as vectors are added (row id =
ntotal before add). We persist that mapping in SQLite (`chunks.faiss_row_id`)
so a search result (row id -> similarity score) can be joined back to full
chunk metadata.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import faiss
import numpy as np

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    chunker_used TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes_doc_id TEXT REFERENCES documents(doc_id),
    is_latest INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_is_latest ON documents(is_latest);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    chunk_type TEXT NOT NULL,
    citation TEXT,
    section_title TEXT,
    page_number INTEGER,
    text TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    references_json TEXT NOT NULL,
    faiss_row_id INTEGER UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    filename TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)


def _load_or_create_index() -> faiss.Index:
    if settings.faiss_index_path.exists():
        return faiss.read_index(str(settings.faiss_index_path))
    return faiss.IndexFlatIP(settings.embedding_dim)


def _save_index(index: faiss.Index):
    faiss.write_index(index, str(settings.faiss_index_path))


def find_document_by_hash(content_hash: str) -> dict | None:
    """Duplicate-upload check -- see docs/AllDevFlow.md Phase 2 notes. Content
    hash (not filename) so the same file under a different name is still
    caught, and a same-named-but-different file isn't."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT doc_id, title, filename, chunker_used, created_at FROM documents WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
    return dict(row) if row else None


def get_document(doc_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def add_document(doc_id: str, title: str, filename: str, chunker_used: str,
                  chunks: list[dict], vectors: np.ndarray, content_hash: str,
                  supersedes_doc_id: str | None = None):
    """Persist a document's chunks + their vectors atomically-ish: FAISS
    write happens first (cheap to redo), then the SQLite transaction records
    the row ids actually used.

    If supersedes_doc_id is given, the old document is flagged is_latest=0
    (its rows are kept, not deleted -- that's what makes this "version
    history" rather than replace-on-reupload) and this new one becomes the
    latest version in that chain. See docs/AllDevFlow.md's "Document
    versioning" section."""
    index = _load_or_create_index()
    start_row = index.ntotal
    index.add(vectors)
    _save_index(index)

    with _connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (doc_id, title, filename, chunker_used, content_hash, created_at,
                supersedes_doc_id, is_latest)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (doc_id, title, filename, chunker_used, content_hash,
             datetime.now(timezone.utc).isoformat(), supersedes_doc_id),
        )
        if supersedes_doc_id:
            conn.execute(
                "UPDATE documents SET is_latest = 0 WHERE doc_id = ?", (supersedes_doc_id,)
            )
        for i, chunk in enumerate(chunks):
            conn.execute(
                """INSERT INTO chunks
                   (chunk_id, doc_id, chunk_type, citation, section_title, page_number,
                    text, word_count, references_json, faiss_row_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk["chunk_id"], doc_id, chunk["chunk_type"], chunk.get("citation"),
                    chunk.get("section_title"), chunk.get("page_number"), chunk["text"],
                    chunk["word_count"], json.dumps(chunk.get("references", [])),
                    start_row + i,
                ),
            )


def delete_document(doc_id: str) -> bool:
    """Deletes a document's row and all its chunk rows. Returns False if the
    doc_id didn't exist.

    Deliberately does NOT touch the FAISS index. Removing rows from a flat
    FAISS index compacts the array, which would shift every subsequent
    vector's position and silently invalidate every other chunk's stored
    faiss_row_id (row ids are assigned as ntotal-at-insert-time, an
    append-only scheme -- see add_document()). Leaving the now-orphaned
    vectors in place is harmless: search() already joins a FAISS hit back to
    a chunk row by faiss_row_id and skips any hit with none (the same
    tolerance that already covers orphans left by a failed upload). Tradeoff:
    the FAISS index file only ever grows, never shrinks -- acceptable for
    this project's corpus size; a real fix would mean rebuilding the index
    from the surviving chunks, deferred as a Phase-2 backlog item (see
    docs/AllDevFlow.md)."""
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not exists:
            return False
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return True


def compact_index() -> dict:
    """Rebuilds the FAISS index containing only the vectors backing
    currently-live chunk rows, dropping every orphaned vector accumulated by
    past deletes/supersedes/schema-reset re-ingests -- the tradeoff
    documented (and deferred) in delete_document()'s docstring. Measured on
    this project's dev corpus before ever running: 3,035 vectors in the
    index for only 1,463 live chunks -- more than half dead weight, silently
    shrinking the effective top_k of every query (see docs/AllDevFlow.md,
    2026-09-04).

    Reconstructs each live vector directly from the existing flat index
    (`IndexFlatIP` supports `reconstruct()` natively -- no re-embedding
    needed) and reassigns sequential `faiss_row_id`s to match the new,
    compacted index. Intended to be run offline via
    `backend/scripts/compact_faiss_index.py`, not exposed as an HTTP
    endpoint -- this is a maintenance operation, not something a request
    should trigger.

    Ordering matters for safety: the new index is fully built and written to
    a temp file, and only swapped into place with a single `os.replace()`
    as the very last step, after the SQLite row-id updates have already
    committed -- so the existing (larger but valid) index file stays intact
    for as long as possible if anything goes wrong partway through. Run with
    the backend stopped."""
    old_index = _load_or_create_index()
    before = old_index.ntotal

    with _connect() as conn:
        rows = conn.execute(
            "SELECT chunk_id, faiss_row_id FROM chunks ORDER BY faiss_row_id"
        ).fetchall()

    new_index = faiss.IndexFlatIP(settings.embedding_dim)
    id_updates = []
    for row in rows:
        vector = old_index.reconstruct(int(row["faiss_row_id"]))
        new_row_id = new_index.ntotal
        new_index.add(np.expand_dims(vector, axis=0))
        id_updates.append((new_row_id, row["chunk_id"]))

    tmp_path = settings.faiss_index_path.parent / (settings.faiss_index_path.name + ".compacting")
    faiss.write_index(new_index, str(tmp_path))

    with _connect() as conn:
        conn.executemany("UPDATE chunks SET faiss_row_id = ? WHERE chunk_id = ?", id_updates)

    os.replace(tmp_path, settings.faiss_index_path)

    return {"before": before, "after": new_index.ntotal, "chunks_remapped": len(id_updates)}


def list_documents(include_all: bool = False) -> list[dict]:
    """By default returns only the latest version of each document (a
    superseded version is hidden, not deleted). Pass include_all=True to see
    every version, e.g. for a version-history view."""
    where = "" if include_all else "WHERE d.is_latest = 1"
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT d.doc_id, d.title, d.filename, d.chunker_used, d.created_at,
                       d.is_latest, d.supersedes_doc_id,
                       COUNT(c.chunk_id) AS chunk_count
                FROM documents d LEFT JOIN chunks c ON c.doc_id = d.doc_id
                {where}
                GROUP BY d.doc_id ORDER BY d.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_document_versions(doc_id: str) -> list[dict]:
    """Walks the supersedes_doc_id chain in both directions from doc_id and
    returns every version in that chain, oldest first. Returns [] if doc_id
    doesn't exist."""
    doc = get_document(doc_id)
    if not doc:
        return []

    with _connect() as conn:
        # walk backward to find the root (oldest) version
        current = doc
        while current["supersedes_doc_id"]:
            row = conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (current["supersedes_doc_id"],)
            ).fetchone()
            if row is None:
                break
            current = dict(row)
        root_id = current["doc_id"]

        # walk forward from the root collecting the whole chain
        chain = []
        next_id = root_id
        while next_id:
            row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (next_id,)).fetchone()
            if row is None:
                break
            chain.append(dict(row))
            successor = conn.execute(
                "SELECT doc_id FROM documents WHERE supersedes_doc_id = ?", (next_id,)
            ).fetchone()
            next_id = successor["doc_id"] if successor else None

    return chain


def get_document_chunks(doc_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY faiss_row_id", (doc_id,)
        ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def _row_to_chunk(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["references"] = json.loads(d.pop("references_json"))
    return d


def create_job(job_id: str, filename: str):
    """Registers a queued ingest job -- see routers/upload.py, which now
    returns 202 + job_id immediately and runs the actual extract/chunk/embed
    pipeline in a FastAPI BackgroundTask, since that pipeline can take
    seconds to minutes per document (docs/AllDevFlow.md backlog)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO jobs (job_id, status, filename, result_json, error, created_at, updated_at)
               VALUES (?, 'queued', ?, NULL, NULL, ?, ?)""",
            (job_id, filename, now, now),
        )


def update_job(job_id: str, status: str, result: dict | None = None, error: str | None = None):
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, result_json = ?, error = ?, updated_at = ? WHERE job_id = ?",
            (status, json.dumps(result) if result is not None else None, error,
             datetime.now(timezone.utc).isoformat(), job_id),
        )


def get_job(job_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    result_json = d.pop("result_json")
    d["result"] = json.loads(result_json) if result_json else None
    return d


def search(query_vector: np.ndarray, top_k: int) -> list[tuple[dict, str, float]]:
    """Returns list of (chunk_dict, doc_title, similarity_score)."""
    index = _load_or_create_index()
    if index.ntotal == 0:
        return []

    scores, row_ids = index.search(np.expand_dims(query_vector, axis=0), min(top_k, index.ntotal))
    scores, row_ids = scores[0], row_ids[0]

    results = []
    with _connect() as conn:
        for score, row_id in zip(scores, row_ids):
            if row_id == -1:
                continue
            chunk_row = conn.execute(
                "SELECT * FROM chunks WHERE faiss_row_id = ?", (int(row_id),)
            ).fetchone()
            if chunk_row is None:
                continue
            doc_row = conn.execute(
                "SELECT title, is_latest FROM documents WHERE doc_id = ?", (chunk_row["doc_id"],)
            ).fetchone()
            if doc_row is None or not doc_row["is_latest"]:
                # superseded version -- see docs/AllDevFlow.md "Document
                # versioning": retrieval only surfaces the current version of
                # each document, same tolerance pattern as orphaned rows.
                continue
            results.append((_row_to_chunk(chunk_row), doc_row["title"], float(score)))
    return results

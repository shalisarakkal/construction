"""Vector index + SQLite metadata store, per dream.md section 3.2 (FAISS,
Pinecone, or Weaviate for vectors, SQLite/Postgres for metadata since none
of the three vector backends store full chunk metadata itself). Which
vector backend is active is controlled by RAG_VECTOR_STORE_PROVIDER
("faiss", "pinecone", or "weaviate") -- see add_document()/search()/
delete_document(), each of which branches on settings.vector_store_provider,
same pattern as llm.py's provider switch. Switching this setting does NOT
migrate existing vectors between backends -- see docs/AllDevFlow.md's
"Phase 5" section for why that's a separate (not yet built) migration
script, deferred as Phase 5a.

FAISS row ids are assigned sequentially as vectors are added (row id =
ntotal before add) and persisted in SQLite (`chunks.faiss_row_id`) so a
search result (row id -> similarity score) can be joined back to full chunk
metadata. Pinecone instead addresses vectors directly by `chunk_id` (its
upsert/query/delete all take arbitrary string ids). Weaviate requires a
UUID per object, so its chunk_id is deterministically hashed into one via
`generate_uuid5()` and also stored as a property so a query result can be
read back to the original chunk_id without needing the reverse mapping.
Neither Pinecone nor Weaviate mode needs `faiss_row_id` for lookups -- it's
still populated with a filler sequential value in both to satisfy the
column's NOT NULL UNIQUE constraint without a schema migration, but is
never read back outside FAISS mode.
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


_pinecone_index_handle = None


def _pinecone_index():
    """Lazily creates the Pinecone client + serverless index and caches the
    handle for reuse within this process. Tests monkeypatch this function
    directly rather than exercising the real client, same seam pattern as
    llm.py's _anthropic_chat/_ollama_chat."""
    global _pinecone_index_handle
    if _pinecone_index_handle is not None:
        return _pinecone_index_handle

    from pinecone import Pinecone, ServerlessSpec

    client = Pinecone(api_key=settings.pinecone_api_key)
    if not client.indexes.exists(name=settings.pinecone_index_name):
        client.indexes.create(
            name=settings.pinecone_index_name,
            dimension=settings.embedding_dim,
            metric="cosine",  # embeddings.py normalizes vectors, so this matches FAISS's IndexFlatIP scores exactly
            spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
            timeout=60,
        )
    _pinecone_index_handle = client.Index(name=settings.pinecone_index_name)
    return _pinecone_index_handle


_weaviate_collection_handle = None


def _weaviate_collection():
    """Lazily creates the Weaviate Cloud client + collection and caches the
    handle for reuse within this process. Tests monkeypatch this function
    directly, same seam pattern as _pinecone_index()/llm.py's
    _anthropic_chat/_ollama_chat.

    Vector index type is `hfresh`, not the more commonly-documented `hnsw`
    -- discovered live against a real Weaviate Cloud cluster created
    2026-09-04, which rejected `hnsw` outright (422 CONFIG_NOT_ALLOWED:
    "hnsw is not allowed for vector_index_type. Allowed values: hfresh.").
    Newer Weaviate Cloud serverless clusters apparently only allow `hfresh`
    now; if this ever needs to run against an older cluster or self-hosted
    instance that only supports `hnsw`, that'll need to become configurable
    rather than hardcoded. Uses the current non-deprecated `vector_config`
    argument (the older separate `vectorizer_config`/`vector_index_config`
    arguments still work but log a DeprecationWarning as of client v4.23).

    We supply our own vectors (same reason as Pinecone's plain index -- no
    built-in text vectorizer module is involved). chunk_id is stored as a
    property (in addition to being hashed into the object's UUID via
    generate_uuid5) purely so a query result can be read back to its
    chunk_id directly, without needing a reverse UUID lookup."""
    global _weaviate_collection_handle
    if _weaviate_collection_handle is not None:
        return _weaviate_collection_handle

    import weaviate
    from weaviate.classes.config import Configure, DataType, Property, VectorDistances
    from weaviate.classes.init import Auth

    client = weaviate.connect_to_weaviate_cloud(
        cluster_url=settings.weaviate_cluster_url,
        auth_credentials=Auth.api_key(settings.weaviate_api_key),
    )
    if not client.collections.exists(settings.weaviate_collection_name):
        client.collections.create(
            name=settings.weaviate_collection_name,
            properties=[
                Property(name="chunk_id", data_type=DataType.TEXT),
                Property(name="doc_id", data_type=DataType.TEXT),
            ],
            vector_config=Configure.Vectors.self_provided(
                vector_index_config=Configure.VectorIndex.hfresh(distance_metric=VectorDistances.COSINE)
            ),
        )
    _weaviate_collection_handle = client.collections.get(settings.weaviate_collection_name)
    return _weaviate_collection_handle


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
    row_ids = None
    if settings.vector_store_provider == "pinecone":
        _pinecone_index().upsert(vectors=[
            (chunk["chunk_id"], vector.tolist(), {"doc_id": doc_id})
            for chunk, vector in zip(chunks, vectors)
        ])
    elif settings.vector_store_provider == "weaviate":
        from weaviate.classes.data import DataObject
        from weaviate.util import generate_uuid5

        _weaviate_collection().data.insert_many([
            DataObject(
                uuid=generate_uuid5(chunk["chunk_id"]),
                properties={"chunk_id": chunk["chunk_id"], "doc_id": doc_id},
                vector=vector.tolist(),
            )
            for chunk, vector in zip(chunks, vectors)
        ])
    else:
        index = _load_or_create_index()
        start_row = index.ntotal
        index.add(vectors)
        _save_index(index)
        row_ids = list(range(start_row, start_row + len(chunks)))

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
        if row_ids is None:
            # Pinecone mode: faiss_row_id is unused filler -- see module docstring.
            next_row = conn.execute("SELECT COALESCE(MAX(faiss_row_id), -1) + 1 AS n FROM chunks").fetchone()["n"]
            row_ids = list(range(next_row, next_row + len(chunks)))
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
                    row_ids[i],
                ),
            )


def delete_document(doc_id: str) -> bool:
    """Deletes a document's row and all its chunk rows. Returns False if the
    doc_id didn't exist.

    FAISS mode deliberately does NOT touch the FAISS index. Removing rows
    from a flat FAISS index compacts the array, which would shift every
    subsequent vector's position and silently invalidate every other
    chunk's stored faiss_row_id (row ids are assigned as ntotal-at-insert-
    time, an append-only scheme -- see add_document()). Leaving the
    now-orphaned vectors in place is harmless: search() already joins a
    FAISS hit back to a chunk row by faiss_row_id and skips any hit with
    none (the same tolerance that already covers orphans left by a failed
    upload). Tradeoff: the FAISS index file only ever grows, never shrinks
    -- acceptable for this project's corpus size; a real fix would mean
    rebuilding the index from the surviving chunks, see compact_index().

    Pinecone and Weaviate mode do NOT have this tradeoff: both support
    deleting individual vectors by id without disturbing anything else, so
    this issues a real delete call against whichever is active -- no orphan
    accumulation, and compact_index() is a FAISS-only concept in either
    cloud mode."""
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not exists:
            return False
        chunk_ids = [
            r["chunk_id"] for r in conn.execute(
                "SELECT chunk_id FROM chunks WHERE doc_id = ?", (doc_id,)
            ).fetchall()
        ]

    if chunk_ids and settings.vector_store_provider == "pinecone":
        _pinecone_index().delete(ids=chunk_ids)
    elif chunk_ids and settings.vector_store_provider == "weaviate":
        from weaviate.classes.query import Filter
        from weaviate.util import generate_uuid5

        uuids = [generate_uuid5(cid) for cid in chunk_ids]
        _weaviate_collection().data.delete_many(where=Filter.by_id().contains_any(uuids))

    with _connect() as conn:
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
    the backend stopped.

    FAISS-only: neither Pinecone nor Weaviate mode ever accumulates orphaned
    vectors in the first place (delete_document() deletes them for real in
    both), so there's nothing to compact."""
    if settings.vector_store_provider != "faiss":
        raise RuntimeError(
            "compact_index() is FAISS-only; RAG_VECTOR_STORE_PROVIDER is "
            f"'{settings.vector_store_provider}', which doesn't accumulate orphaned vectors."
        )
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


def search(
    query_vector: np.ndarray, top_k: int, doc_ids: list[str] | None = None
) -> list[tuple[dict, str, float]]:
    """Returns list of (chunk_dict, doc_title, similarity_score).

    doc_ids, when given, scopes the search to just those documents -- see
    docs/AllDevFlow.md's "Scope Q&A to selected document(s)" section. An
    empty list is treated the same as None (search everything), since the
    frontend sends [] to mean "nothing explicitly selected," not "search
    nothing."""
    if not doc_ids:
        doc_ids = None
    if settings.vector_store_provider == "pinecone":
        return _search_pinecone(query_vector, top_k, doc_ids)
    if settings.vector_store_provider == "weaviate":
        return _search_weaviate(query_vector, top_k, doc_ids)
    return _search_faiss(query_vector, top_k, doc_ids)


def _search_faiss(
    query_vector: np.ndarray, top_k: int, doc_ids: list[str] | None
) -> list[tuple[dict, str, float]]:
    index = _load_or_create_index()
    if index.ntotal == 0:
        return []

    # IndexFlatIP is an exact brute-force scan -- it computes a score against
    # every vector regardless of k, so asking for ntotal results instead of
    # top_k costs nothing extra. Doing that (rather than a smaller k) is what
    # makes post-hoc doc_id filtering below correct: a smaller k could drop
    # every result from the requested document(s) before filtering ever runs.
    k = index.ntotal if doc_ids else min(top_k, index.ntotal)
    scores, row_ids = index.search(np.expand_dims(query_vector, axis=0), k)
    scores, row_ids = scores[0], row_ids[0]

    doc_id_set = set(doc_ids) if doc_ids else None
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
            if doc_id_set is not None and chunk_row["doc_id"] not in doc_id_set:
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
            if len(results) == top_k:
                break
    return results


def _search_pinecone(
    query_vector: np.ndarray, top_k: int, doc_ids: list[str] | None
) -> list[tuple[dict, str, float]]:
    query_kwargs = {}
    if doc_ids:
        query_kwargs["filter"] = {"doc_id": {"$in": doc_ids}}
    response = _pinecone_index().query(
        vector=query_vector.tolist(), top_k=top_k, include_values=False,
        include_metadata=False, **query_kwargs,
    )

    results = []
    with _connect() as conn:
        for match in response.matches:
            chunk_row = conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (match.id,)
            ).fetchone()
            if chunk_row is None:
                continue
            doc_row = conn.execute(
                "SELECT title, is_latest FROM documents WHERE doc_id = ?", (chunk_row["doc_id"],)
            ).fetchone()
            if doc_row is None or not doc_row["is_latest"]:
                continue
            results.append((_row_to_chunk(chunk_row), doc_row["title"], float(match.score)))
    return results


def _search_weaviate(
    query_vector: np.ndarray, top_k: int, doc_ids: list[str] | None
) -> list[tuple[dict, str, float]]:
    from weaviate.classes.query import Filter, MetadataQuery

    query_kwargs = {}
    if doc_ids:
        query_kwargs["filters"] = Filter.by_property("doc_id").contains_any(doc_ids)
    response = _weaviate_collection().query.near_vector(
        near_vector=query_vector.tolist(),
        limit=top_k,
        return_metadata=MetadataQuery(distance=True),
        return_properties=["chunk_id"],
        **query_kwargs,
    )

    results = []
    with _connect() as conn:
        for obj in response.objects:
            chunk_row = conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (obj.properties["chunk_id"],)
            ).fetchone()
            if chunk_row is None:
                continue
            doc_row = conn.execute(
                "SELECT title, is_latest FROM documents WHERE doc_id = ?", (chunk_row["doc_id"],)
            ).fetchone()
            if doc_row is None or not doc_row["is_latest"]:
                continue
            # Weaviate returns cosine distance, not similarity -- convert so
            # scores line up with FAISS's/Pinecone's similarity scale (the
            # confidence-badge thresholds are tuned against that scale).
            score = 1.0 - obj.metadata.distance
            results.append((_row_to_chunk(chunk_row), doc_row["title"], score))
    return results

import numpy as np
import pytest

from app import vector_store
from app.config import settings

pytestmark = pytest.mark.usefixtures("isolated_storage")


def _unit_vector(index: int) -> np.ndarray:
    v = np.zeros(settings.embedding_dim, dtype="float32")
    v[index] = 1.0
    return v


def _add_doc(doc_id: str, title: str, vector: np.ndarray, content_hash: str, supersedes_doc_id: str | None = None):
    chunk = {
        "chunk_id": f"{doc_id}_0",
        "chunk_type": "generic",
        "citation": None,
        "section_title": None,
        "page_number": 1,
        "text": f"Text for {title}",
        "word_count": 3,
        "references": [],
    }
    vector_store.add_document(
        doc_id, title, f"{title}.txt", "generic", [chunk],
        np.expand_dims(vector, axis=0), content_hash,
        supersedes_doc_id=supersedes_doc_id,
    )


def test_add_document_and_get_document_round_trip():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")

    doc = vector_store.get_document("doc1")

    assert doc["title"] == "Doc One"
    assert doc["is_latest"] == 1
    assert vector_store.get_document("missing") is None


def test_find_document_by_hash():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash-abc")

    found = vector_store.find_document_by_hash("hash-abc")
    assert found["doc_id"] == "doc1"
    assert vector_store.find_document_by_hash("hash-xyz") is None


def test_search_returns_empty_for_empty_index():
    assert vector_store.search(_unit_vector(0), top_k=5) == []


def test_search_skips_orphaned_faiss_rows():
    """delete_document() intentionally leaves the FAISS vector in place (see
    its docstring) -- search() must tolerate a hit whose chunk row is gone
    rather than erroring, and simply exclude it from results."""
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    vector_store.delete_document("doc1")

    results = vector_store.search(_unit_vector(0), top_k=2)

    titles = [doc_title for _chunk, doc_title, _score in results]
    assert "Doc One" not in titles
    assert titles == ["Doc Two"]


def test_search_hides_superseded_documents():
    _add_doc("doc1", "Doc One v1", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc One v2", _unit_vector(0), "hash2", supersedes_doc_id="doc1")

    # Query with doc1's exact original vector (a perfect-similarity match)
    # -- it must still be excluded because it's no longer is_latest.
    results = vector_store.search(_unit_vector(0), top_k=5)

    titles = [doc_title for _chunk, doc_title, _score in results]
    assert titles == ["Doc One v2"]


def test_delete_document_removes_metadata_but_keeps_faiss_vector():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    index_before = vector_store._load_or_create_index().ntotal

    deleted = vector_store.delete_document("doc1")

    assert deleted is True
    assert vector_store.get_document("doc1") is None
    assert vector_store.get_document_chunks("doc1") == []
    # FAISS index only ever grows -- see delete_document()'s docstring.
    assert vector_store._load_or_create_index().ntotal == index_before


def test_delete_document_returns_false_for_unknown_doc():
    assert vector_store.delete_document("does-not-exist") is False


def test_compact_index_drops_orphaned_vectors_and_keeps_live_chunks_searchable():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")
    vector_store.delete_document("doc1")  # leaves doc1's vector orphaned in FAISS

    before_ntotal = vector_store._load_or_create_index().ntotal
    assert before_ntotal == 2  # both vectors still physically present

    report = vector_store.compact_index()

    assert report == {"before": 2, "after": 1, "chunks_remapped": 1}
    assert vector_store._load_or_create_index().ntotal == 1

    results = vector_store.search(_unit_vector(1), top_k=5)
    titles = [doc_title for _chunk, doc_title, _score in results]
    assert titles == ["Doc Two"]


def test_compact_index_is_a_noop_on_an_already_compact_index():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")

    report = vector_store.compact_index()

    assert report == {"before": 1, "after": 1, "chunks_remapped": 1}
    results = vector_store.search(_unit_vector(0), top_k=5)
    assert [doc_title for _chunk, doc_title, _score in results] == ["Doc One"]


def test_get_document_versions_returns_empty_for_unknown_doc():
    assert vector_store.get_document_versions("does-not-exist") == []


def test_get_document_versions_walks_full_chain_from_middle_link():
    _add_doc("v1", "Policy v1", _unit_vector(0), "hash1")
    _add_doc("v2", "Policy v2", _unit_vector(1), "hash2", supersedes_doc_id="v1")
    _add_doc("v3", "Policy v3", _unit_vector(2), "hash3", supersedes_doc_id="v2")

    chain = vector_store.get_document_versions("v2")

    assert [d["doc_id"] for d in chain] == ["v1", "v2", "v3"]

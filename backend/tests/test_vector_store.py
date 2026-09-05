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


def test_search_with_doc_ids_scopes_to_requested_documents():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")
    _add_doc("doc3", "Doc Three", _unit_vector(2), "hash3")

    # A query vector closest to doc1, but scoped to doc2/doc3 only -- doc1
    # must not come back even though it would otherwise be the top hit.
    results = vector_store.search(_unit_vector(0), top_k=5, doc_ids=["doc2", "doc3"])

    titles = {doc_title for _chunk, doc_title, _score in results}
    assert titles == {"Doc Two", "Doc Three"}


def test_search_with_empty_doc_ids_searches_everything():
    """[] means "nothing explicitly selected" (the frontend's default), not
    "search nothing" -- same as doc_ids=None."""
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")

    results = vector_store.search(_unit_vector(0), top_k=5, doc_ids=[])

    assert [title for _chunk, title, _score in results] == ["Doc One"]


def test_search_with_doc_ids_matching_nothing_returns_empty():
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")

    results = vector_store.search(_unit_vector(0), top_k=5, doc_ids=["does-not-exist"])

    assert results == []


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


# ---------------------------------------------------------------------------
# Pinecone provider path -- see vector_store.py's module docstring.
# `_pinecone_index()` is monkeypatched to a fake in-memory index (no real
# API key/network needed), same seam pattern as llm.py's tests mocking
# _anthropic_chat/_ollama_chat.
# ---------------------------------------------------------------------------


class _FakeScoredVector:
    def __init__(self, id, score):
        self.id = id
        self.score = score


class _FakeQueryResponse:
    def __init__(self, matches):
        self.matches = matches


class _FakePineconeIndex:
    """In-memory stand-in for a Pinecone Index: cosine similarity computed
    directly (vectors here are unit basis vectors, so a dot product is
    exact), no network calls."""

    def __init__(self):
        self.vectors: dict[str, list[float]] = {}
        self.metadata: dict[str, dict] = {}
        self.deleted_ids: list[str] = []

    def upsert(self, vectors):
        for chunk_id, values, *rest in vectors:
            self.vectors[chunk_id] = values
            self.metadata[chunk_id] = rest[0] if rest else {}

    def query(self, *, vector, top_k, include_values=False, include_metadata=False, filter=None):
        allowed_doc_ids = set(filter["doc_id"]["$in"]) if filter else None
        scored = [
            (chunk_id, float(np.dot(values, vector)))
            for chunk_id, values in self.vectors.items()
            if allowed_doc_ids is None or self.metadata.get(chunk_id, {}).get("doc_id") in allowed_doc_ids
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        matches = [_FakeScoredVector(cid, score) for cid, score in scored[:top_k]]
        return _FakeQueryResponse(matches)

    def delete(self, *, ids):
        self.deleted_ids.extend(ids)
        for chunk_id in ids:
            self.vectors.pop(chunk_id, None)
            self.metadata.pop(chunk_id, None)


@pytest.fixture
def pinecone_provider(monkeypatch):
    monkeypatch.setattr(settings, "vector_store_provider", "pinecone")
    fake_index = _FakePineconeIndex()
    monkeypatch.setattr(vector_store, "_pinecone_index", lambda: fake_index)
    return fake_index


def test_pinecone_add_and_search_round_trip(pinecone_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    results = vector_store.search(_unit_vector(0), top_k=5)

    assert [title for _chunk, title, _score in results] == ["Doc One", "Doc Two"]
    assert pinecone_provider.vectors.keys() == {"doc1_0", "doc2_0"}


def test_pinecone_search_with_doc_ids_scopes_to_requested_documents(pinecone_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    results = vector_store.search(_unit_vector(0), top_k=5, doc_ids=["doc2"])

    assert [title for _chunk, title, _score in results] == ["Doc Two"]


def test_pinecone_delete_document_removes_vectors_from_index(pinecone_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    deleted = vector_store.delete_document("doc1")

    assert deleted is True
    assert pinecone_provider.deleted_ids == ["doc1_0"]
    assert "doc1_0" not in pinecone_provider.vectors
    results = vector_store.search(_unit_vector(0), top_k=5)
    assert [title for _chunk, title, _score in results] == ["Doc Two"]


def test_pinecone_search_hides_superseded_documents(pinecone_provider):
    _add_doc("doc1", "Doc One v1", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc One v2", _unit_vector(0), "hash2", supersedes_doc_id="doc1")

    results = vector_store.search(_unit_vector(0), top_k=5)

    assert [title for _chunk, title, _score in results] == ["Doc One v2"]


def test_compact_index_raises_for_non_faiss_provider(pinecone_provider):
    with pytest.raises(RuntimeError, match="FAISS-only"):
        vector_store.compact_index()


# ---------------------------------------------------------------------------
# Weaviate provider path -- same seam-monkeypatching approach as Pinecone
# above, via a fake in-memory collection (no real cluster URL/API key/
# network needed).
# ---------------------------------------------------------------------------


class _FakeWeaviateObject:
    def __init__(self, uuid, chunk_id, distance):
        self.uuid = uuid
        self.properties = {"chunk_id": chunk_id}
        self.metadata = type("Metadata", (), {"distance": distance})()


class _FakeWeaviateQueryResponse:
    def __init__(self, objects):
        self.objects = objects


class _FakeWeaviateData:
    def __init__(self, store):
        self._store = store

    def insert_many(self, objects):
        for obj in objects:
            self._store[str(obj.uuid)] = (
                obj.properties["chunk_id"], obj.properties.get("doc_id"), obj.vector
            )

    def delete_many(self, where):
        for uuid in where.value:
            self._store.pop(uuid, None)


class _FakeWeaviateQuery:
    def __init__(self, store):
        self._store = store

    def near_vector(self, *, near_vector, limit, return_metadata=None, return_properties=None,
                     filters=None):
        allowed_doc_ids = set(filters.value) if filters else None
        # Cosine distance = 1 - cosine similarity; vectors here are unit
        # basis vectors, so a plain dot product is an exact cosine similarity.
        scored = [
            (uuid, chunk_id, 1.0 - float(np.dot(vector, near_vector)))
            for uuid, (chunk_id, doc_id, vector) in self._store.items()
            if allowed_doc_ids is None or doc_id in allowed_doc_ids
        ]
        scored.sort(key=lambda triple: triple[2])
        objects = [
            _FakeWeaviateObject(uuid, chunk_id, distance)
            for uuid, chunk_id, distance in scored[:limit]
        ]
        return _FakeWeaviateQueryResponse(objects)


class _FakeWeaviateCollection:
    """In-memory stand-in for a Weaviate Collection, keyed by uuid like the
    real one (generate_uuid5(chunk_id) is still used by vector_store.py to
    compute that key, so this fake exercises the same id-derivation code)."""

    def __init__(self):
        self.store: dict[str, tuple[str, str | None, list[float]]] = {}
        self.data = _FakeWeaviateData(self.store)
        self.query = _FakeWeaviateQuery(self.store)


@pytest.fixture
def weaviate_provider(monkeypatch):
    monkeypatch.setattr(settings, "vector_store_provider", "weaviate")
    fake_collection = _FakeWeaviateCollection()
    monkeypatch.setattr(vector_store, "_weaviate_collection", lambda: fake_collection)
    return fake_collection


def test_weaviate_add_and_search_round_trip(weaviate_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    results = vector_store.search(_unit_vector(0), top_k=5)

    assert [title for _chunk, title, _score in results] == ["Doc One", "Doc Two"]
    assert results[0][2] == pytest.approx(1.0)  # exact match -> distance 0 -> score 1.0
    stored_chunk_ids = {chunk_id for chunk_id, _doc_id, _vector in weaviate_provider.store.values()}
    assert stored_chunk_ids == {"doc1_0", "doc2_0"}


def test_weaviate_search_with_doc_ids_scopes_to_requested_documents(weaviate_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    results = vector_store.search(_unit_vector(0), top_k=5, doc_ids=["doc2"])

    assert [title for _chunk, title, _score in results] == ["Doc Two"]


def test_weaviate_delete_document_removes_vectors_from_collection(weaviate_provider):
    _add_doc("doc1", "Doc One", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc Two", _unit_vector(1), "hash2")

    deleted = vector_store.delete_document("doc1")

    assert deleted is True
    remaining_chunk_ids = {chunk_id for chunk_id, _doc_id, _vector in weaviate_provider.store.values()}
    assert remaining_chunk_ids == {"doc2_0"}
    results = vector_store.search(_unit_vector(0), top_k=5)
    assert [title for _chunk, title, _score in results] == ["Doc Two"]


def test_weaviate_search_hides_superseded_documents(weaviate_provider):
    _add_doc("doc1", "Doc One v1", _unit_vector(0), "hash1")
    _add_doc("doc2", "Doc One v2", _unit_vector(0), "hash2", supersedes_doc_id="doc1")

    results = vector_store.search(_unit_vector(0), top_k=5)

    assert [title for _chunk, title, _score in results] == ["Doc One v2"]


def test_compact_index_raises_for_weaviate_provider(weaviate_provider):
    with pytest.raises(RuntimeError, match="FAISS-only"):
        vector_store.compact_index()

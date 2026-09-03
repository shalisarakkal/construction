def _upload(client, filename, content):
    resp = client.post("/upload", files={"file": (filename, content.encode(), "text/plain")})
    assert resp.status_code == 200
    return resp.json()


def test_list_documents_empty(client):
    resp = client.get("/documents")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_documents_returns_uploaded_docs_newest_first(client):
    first = _upload(client, "first.txt", "First document about fire exits.")
    second = _upload(client, "second.txt", "Second document about handrail height.")

    resp = client.get("/documents")

    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()]
    assert titles == ["second.txt", "first.txt"]

    by_id = {d["doc_id"]: d for d in resp.json()}
    assert by_id[first["doc_id"]]["chunk_count"] == 1
    assert by_id[second["doc_id"]]["chunk_count"] == 1
    assert by_id[first["doc_id"]]["is_latest"] is True


def test_list_documents_default_hides_superseded_versions(client):
    v1 = _upload(client, "policy_v1.txt", "Policy version one.")
    v2_resp = client.post(
        "/upload",
        files={"file": ("policy_v2.txt", b"Policy version two.", "text/plain")},
        data={"supersedes": v1["doc_id"]},
    )
    assert v2_resp.status_code == 200
    v2 = v2_resp.json()

    default_resp = client.get("/documents")
    default_titles = {d["title"] for d in default_resp.json()}
    assert default_titles == {"policy_v2.txt"}

    all_resp = client.get("/documents", params={"include_all": "true"})
    all_titles = {d["title"] for d in all_resp.json()}
    assert all_titles == {"policy_v1.txt", "policy_v2.txt"}

    by_id = {d["doc_id"]: d for d in all_resp.json()}
    assert by_id[v1["doc_id"]]["is_latest"] is False
    assert by_id[v2["doc_id"]]["is_latest"] is True


def test_get_versions_returns_404_for_unknown_document(client):
    resp = client.get("/documents/does-not-exist/versions")

    assert resp.status_code == 404


def test_get_versions_returns_chain_oldest_first(client):
    v1 = _upload(client, "policy_v1.txt", "Policy version one.")
    v2_resp = client.post(
        "/upload",
        files={"file": ("policy_v2.txt", b"Policy version two.", "text/plain")},
        data={"supersedes": v1["doc_id"]},
    )
    v2 = v2_resp.json()

    resp = client.get(f"/documents/{v1['doc_id']}/versions")

    assert resp.status_code == 200
    body = resp.json()
    assert [d["doc_id"] for d in body] == [v1["doc_id"], v2["doc_id"]]
    assert body[0]["is_latest"] is False
    assert body[1]["is_latest"] is True
    assert body[0]["chunk_count"] == 1


def test_get_chunks_returns_404_for_unknown_document(client):
    resp = client.get("/documents/does-not-exist/chunks")

    assert resp.status_code == 404


def test_get_chunks_returns_chunk_records(client):
    doc = _upload(client, "egress.txt", "Exit doors shall swing in the direction of egress travel.")

    resp = client.get(f"/documents/{doc['doc_id']}/chunks")

    assert resp.status_code == 200
    chunks = resp.json()
    assert len(chunks) == 1
    assert chunks[0]["doc_id"] == doc["doc_id"]
    assert chunks[0]["chunk_type"] == "generic"
    assert "egress" in chunks[0]["text"]
    assert chunks[0]["word_count"] > 0


def test_delete_returns_404_for_unknown_document(client):
    resp = client.delete("/documents/does-not-exist")

    assert resp.status_code == 404


def test_delete_removes_document_and_its_chunks(client):
    doc = _upload(client, "egress.txt", "Exit doors shall swing in the direction of egress travel.")

    delete_resp = client.delete(f"/documents/{doc['doc_id']}")
    assert delete_resp.status_code == 204

    assert client.get("/documents").json() == []
    assert client.get(f"/documents/{doc['doc_id']}/chunks").status_code == 404


def test_delete_frees_up_content_hash_for_reupload(client):
    content = "Exit doors shall swing in the direction of egress travel."
    doc = _upload(client, "egress.txt", content)

    client.delete(f"/documents/{doc['doc_id']}")

    # Same content, previously rejected as a 409 duplicate, should now be
    # accepted since the original document was deleted.
    resp = client.post("/upload", files={"file": ("egress.txt", content.encode(), "text/plain")})
    assert resp.status_code == 200

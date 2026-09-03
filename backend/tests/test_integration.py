from app import llm


def test_full_document_lifecycle(client, monkeypatch):
    """upload -> list -> query (retrieval) -> summary (LLM mocked) -> delete
    -> confirm it's gone everywhere, exercising all four routers together."""
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    upload = client.post(
        "/upload",
        files={"file": ("egress.txt", b"Exit doors shall swing in the direction of egress travel.", "text/plain")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["doc_id"]

    listed = client.get("/documents").json()
    assert [d["doc_id"] for d in listed] == [doc_id]

    query_resp = client.post("/query", json={"question": "Which way do exit doors swing?"})
    assert query_resp.status_code == 200
    assert query_resp.json()["chunks"][0]["doc_title"] == "egress.txt"

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "synthesize_summary", lambda title, context_block: "Doors swing outward for egress.")
    summary_resp = client.post(f"/documents/{doc_id}/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["summary"] == "Doors swing outward for egress."

    delete_resp = client.delete(f"/documents/{doc_id}")
    assert delete_resp.status_code == 204

    assert client.get("/documents").json() == []
    assert client.get(f"/documents/{doc_id}/chunks").status_code == 404
    assert client.post(f"/documents/{doc_id}/summary").status_code == 404

    monkeypatch.setattr(llm, "is_configured", lambda: False)
    empty_query = client.post("/query", json={"question": "Which way do exit doors swing?"})
    assert empty_query.json()["chunks"] == []


def test_replaced_version_is_excluded_from_query_but_kept_in_history(client, monkeypatch):
    """Superseding a document must remove the old version from retrieval
    (query/summary should only ever see the current text) while /versions
    still shows the full history -- ties together upload, query, and
    documents behavior that no single-router test exercises together."""
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    v1 = client.post(
        "/upload",
        files={"file": ("policy_v1.txt", b"Handrail height shall be 34 inches minimum.", "text/plain")},
    )
    assert v1.status_code == 200
    v1_id = v1.json()["doc_id"]

    before = client.post("/query", json={"question": "What is the minimum handrail height?"})
    assert before.json()["chunks"][0]["doc_title"] == "policy_v1.txt"

    v2 = client.post(
        "/upload",
        files={"file": ("policy_v2.txt", b"Handrail height shall be 36 inches minimum.", "text/plain")},
        data={"supersedes": v1_id},
    )
    assert v2.status_code == 200
    v2_id = v2.json()["doc_id"]

    after = client.post("/query", json={"question": "What is the minimum handrail height?"})
    titles = [c["doc_title"] for c in after.json()["chunks"]]
    assert "policy_v1.txt" not in titles
    assert titles == ["policy_v2.txt"]

    default_list = client.get("/documents").json()
    assert [d["doc_id"] for d in default_list] == [v2_id]

    versions = client.get(f"/documents/{v1_id}/versions").json()
    assert [d["doc_id"] for d in versions] == [v1_id, v2_id]
    assert [d["is_latest"] for d in versions] == [False, True]

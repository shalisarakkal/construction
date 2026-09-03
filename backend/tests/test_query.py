from app import llm
from app.routers.query import build_context_block


def test_query_with_no_documents_returns_empty_result(client, monkeypatch):
    # is_configured is irrelevant here (no chunks -> llm is never consulted),
    # but pinned to False anyway so this test can't depend on whatever LLM
    # provider happens to be configured/reachable on the machine running it.
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    resp = client.post("/query", json={"question": "What permits are required?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == "What permits are required?"
    assert body["answer"] is None
    assert body["citations"] == []
    assert body["confidence"] == 0.0
    assert body["llm_used"] is False
    assert body["chunks"] == []


def test_query_retrieves_relevant_chunk_without_llm(client, monkeypatch):
    # Pinning is_configured() False keeps this test on the retrieval path
    # only -- see app/llm.py's module docstring: "the retrieval path is
    # testable without any LLM dependency at all."
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    upload = client.post(
        "/upload",
        files={"file": ("egress.txt", b"Exit doors shall swing in the direction of egress travel.", "text/plain")},
    )
    assert upload.status_code == 200

    resp = client.post("/query", json={"question": "Which direction should exit doors swing?", "top_k": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] is None
    assert body["llm_used"] is False
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["doc_title"] == "egress.txt"
    assert "egress" in body["chunks"][0]["chunk"]["text"]
    assert body["citations"] == ["egress.txt — page 1"]
    assert body["confidence"] > 0


def test_query_synthesizes_answer_when_llm_configured(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)

    captured = {}

    def fake_synthesize_answer(question, context_block):
        captured["question"] = question
        captured["context_block"] = context_block
        return "Canned answer citing the retrieved context."

    monkeypatch.setattr(llm, "synthesize_answer", fake_synthesize_answer)

    upload = client.post(
        "/upload",
        files={"file": ("egress.txt", b"Exit doors shall swing in the direction of egress travel.", "text/plain")},
    )
    assert upload.status_code == 200

    resp = client.post("/query", json={"question": "Which direction should exit doors swing?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_used"] is True
    assert body["answer"] == "Canned answer citing the retrieved context."
    assert captured["question"] == "Which direction should exit doors swing?"
    assert "egress" in captured["context_block"]


def test_query_top_k_limits_chunk_count(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    for i in range(3):
        resp = client.post(
            "/upload",
            files={"file": (f"doc{i}.txt", f"Fire safety requirement number {i} for exit corridors.".encode(), "text/plain")},
        )
        assert resp.status_code == 200

    resp = client.post("/query", json={"question": "fire safety exit corridor requirements", "top_k": 2})

    assert resp.status_code == 200
    assert len(resp.json()["chunks"]) == 2


def test_build_context_block_matches_dream_md_format():
    results = [
        ({"text": "Doors shall be 36 inches wide.", "citation": "N.J.A.C. 5:23-1.1"}, "njac_5_23_1.pdf", 0.9),
        ({"text": "Ramps shall not exceed a 1:12 slope.", "page_number": 4}, "generic_doc.pdf", 0.8),
    ]

    block = build_context_block(results)

    assert "[Doc: njac_5_23_1.pdf, N.J.A.C. 5:23-1.1]\nDoors shall be 36 inches wide." in block
    assert "[Doc: generic_doc.pdf, Page 4]\nRamps shall not exceed a 1:12 slope." in block

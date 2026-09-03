from app import llm

# Single sentence, 14 words -- repeated to build a document whose chunks
# exceed summary.py's MAX_SUMMARY_WORDS (6000), to exercise truncation.
_SENTENCE = "Corridor doors shall have a minimum fire rating of twenty minutes for occupant safety."


def test_summary_returns_503_when_llm_not_configured(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: False)

    resp = client.post("/documents/any-doc-id/summary")

    assert resp.status_code == 503
    assert "LLM provider" in resp.json()["detail"]


def test_summary_returns_404_for_unknown_document(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)

    resp = client.post("/documents/does-not-exist/summary")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_summary_success_not_truncated(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)

    captured = {}

    def fake_synthesize_summary(title, context_block):
        captured["title"] = title
        captured["context_block"] = context_block
        return "This document covers fire door rating requirements."

    monkeypatch.setattr(llm, "synthesize_summary", fake_synthesize_summary)

    upload = client.post(
        "/upload",
        files={"file": ("egress.txt", b"Exit doors shall swing in the direction of egress travel.", "text/plain")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["doc_id"]

    resp = client.post(f"/documents/{doc_id}/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == doc_id
    assert body["title"] == "egress.txt"
    assert body["summary"] == "This document covers fire door rating requirements."
    assert body["chunks_used"] == body["chunks_total"] == 1
    assert body["truncated"] is False
    assert captured["title"] == "egress.txt"
    assert "egress" in captured["context_block"]


def test_summary_truncates_when_over_word_budget(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "synthesize_summary", lambda title, context_block: "Truncated summary.")

    big_text = (_SENTENCE + " ") * 500  # ~7000 words, over the 6000-word cap
    upload = client.post(
        "/upload",
        files={"file": ("big_doc.txt", big_text.encode(), "text/plain")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["doc_id"]
    total_chunks = upload.json()["chunk_count"]
    assert total_chunks > 1  # sanity check the doc actually produced multiple chunks

    resp = client.post(f"/documents/{doc_id}/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_total"] == total_chunks
    assert body["chunks_used"] < body["chunks_total"]
    assert body["truncated"] is True

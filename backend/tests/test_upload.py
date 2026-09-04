from conftest import upload_and_wait


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    import io

    import docx

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_upload_returns_202_with_a_job_id(client):
    resp = client.post(
        "/upload",
        files={"file": ("notes.txt", b"Fire-rated doors in exit corridors shall have a minimum rating.", "text/plain")},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["filename"] == "notes.txt"
    assert body["job_id"]


def test_upload_docx_success(client):
    content = _make_docx_bytes([
        "Addendum 3: Fire Door Requirements",
        "Corridor doors shall have a minimum fire rating of twenty minutes.",
    ])

    body = upload_and_wait(
        client,
        files={"file": ("addendum.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert body["filename"] == "addendum.docx"
    assert body["title"] == "addendum.docx"
    assert body["chunker_used"] == "generic"
    assert body["chunk_count"] == 1
    assert body["ocr_used"] is False
    assert body["doc_id"]

    chunks = client.get(f"/documents/{body['doc_id']}/chunks").json()
    assert len(chunks) == 1
    assert "Fire Door Requirements" in chunks[0]["text"]
    assert "twenty minutes" in chunks[0]["text"]
    # python-docx has no page-break API, so extract_docx_pages returns the
    # whole document as a single page -- generic_chunk numbers it page 1.
    assert chunks[0]["page_number"] == 1


def test_upload_docx_empty_job_errors(client):
    content = _make_docx_bytes([])

    resp = client.post(
        "/upload",
        files={"file": ("blank.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = client.get(f"/upload/jobs/{job_id}").json()
    assert job["status"] == "error"
    assert "No extractable text" in job["error"]


def test_upload_txt_success(client):
    body = upload_and_wait(
        client,
        files={"file": ("notes.txt", b"Fire-rated doors in exit corridors shall have a minimum rating of 20 minutes.", "text/plain")},
    )
    assert body["filename"] == "notes.txt"
    assert body["title"] == "notes.txt"
    assert body["chunker_used"] == "generic"
    assert body["chunk_count"] == 1
    assert body["ocr_used"] is False
    assert body["supersedes_doc_id"] is None
    assert body["doc_id"]


def test_upload_duplicate_content_returns_409(client):
    content = b"Duplicate content check: handrails shall be continuous."
    first = upload_and_wait(client, files={"file": ("a.txt", content, "text/plain")})

    second = client.post("/upload", files={"file": ("b.txt", content, "text/plain")})
    assert second.status_code == 409
    assert first["doc_id"] in second.json()["detail"]


def test_upload_unsupported_extension_returns_400(client):
    resp = client.post(
        "/upload",
        files={"file": ("drawing.dwg", b"not a real dwg", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert ".pdf" in resp.json()["detail"]
    assert ".dwg" in resp.json()["detail"]


def test_upload_empty_document_job_errors(client):
    resp = client.post(
        "/upload",
        files={"file": ("blank.txt", b"   \n\n   ", "text/plain")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = client.get(f"/upload/jobs/{job_id}").json()
    assert job["status"] == "error"
    assert "No extractable text" in job["error"]


def test_upload_supersedes_marks_replacement(client):
    original = upload_and_wait(client, files={"file": ("policy_v1.txt", b"Policy version one text.", "text/plain")})
    original_id = original["doc_id"]

    replacement = upload_and_wait(
        client,
        files={"file": ("policy_v2.txt", b"Policy version two text.", "text/plain")},
        data={"supersedes": original_id},
    )
    assert replacement["supersedes_doc_id"] == original_id


def test_upload_supersedes_missing_doc_returns_422(client):
    resp = client.post(
        "/upload",
        files={"file": ("policy_v2.txt", b"Policy version two text.", "text/plain")},
        data={"supersedes": "does-not-exist"},
    )
    assert resp.status_code == 422


def test_upload_job_status_returns_404_for_unknown_job(client):
    resp = client.get("/upload/jobs/does-not-exist")
    assert resp.status_code == 404

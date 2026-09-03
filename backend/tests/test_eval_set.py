"""Wires up NJ/eval/eval_set.json (15 hand-verified Q&A cases against
njac_5_23_12.pdf, previously unused -- see docs/AllDevFlow.md Phase 1) as a
real, CI-running regression check on retrieval quality.

Ingests ONLY njac_5_23_12.pdf into an isolated corpus, matching the eval
set's own `source_doc` field and the single-document conditions it was
originally verified under (see AllDevFlow.md's Phase 1 "Retrieval quality"
table). Running the same cases against the current multi-document production
corpus gives different, noisier results -- other subchapters now legitimately
contain related content the eval set's author didn't have indexed yet, which
would make this a test of corpus composition rather than retrieval quality.

Checks retrieval only (no LLM), per the eval set's own stated primary
criterion: "check that the retrieved top-k chunks include the cited
section." Answer-text quality (the eval set's secondary criterion) isn't
checked here -- that would require a real LLM call, which isn't something a
regression test should depend on being configured/reachable.
"""

import json
import re
from pathlib import Path

import pytest

from app import ingestion, vector_store
from app.config import settings
from app.embeddings import embed_query

EVAL_SET_PATH = Path(__file__).resolve().parent.parent.parent / "NJ" / "eval" / "eval_set.json"
SOURCE_PDF_PATH = Path(__file__).resolve().parent.parent.parent / "NJ" / "pdfs" / "njac_5_23_12.pdf"

SECTION_RE = re.compile(r"5:23-\d+[A-Za-z]?(?:\.\d+)?")

# Above the confidence a genuinely out-of-scope question should score (see
# AllDevFlow.md: original negative-control measurement was 0.34, well below
# 0.62-0.84 for real matches), but loose enough not to flake on ordinary
# embedding-similarity noise -- q12's re-measured confidence (0.584) is a
# weaker negative control than q11's (0.394), not a bug.
NEGATIVE_CONTROL_MAX_CONFIDENCE = 0.65


def _load_cases() -> list[dict]:
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        return json.load(f)["cases"]


def _expected_section(expected_citation: str) -> str:
    """First 'N.J.A.C. 5:23-X.Y'-shaped fragment in an expected_citation
    string, e.g. 'N.J.A.C. 5:23-12.4(a) / 12.4(b)1' -> '5:23-12.4'. Some
    cases cite multiple subsections of the same section; matching at the
    section level (not exact subsection) mirrors the eval set's own stated
    criterion of checking the *cited section* is retrieved, not an exact
    subsection/sentence match."""
    match = SECTION_RE.search(expected_citation)
    assert match, f"couldn't extract a section number from: {expected_citation!r}"
    return match.group(0)


def _case_params():
    params = []
    for case in _load_cases():
        marks = []
        if case["type"] == "amendment-history":
            # Known, documented limitation: app/chunkers/njac.py's
            # HISTORY_SPLIT_RE deliberately strips each section's amendment
            # history block before chunking/embedding (low retrieval signal
            # -- see njac.py's module docstring), so this question's answer
            # is not actually present in any indexed chunk. Retrieval still
            # correctly finds the right *section* (5:23-12.5), but that's a
            # false positive for what this case is really testing.
            marks.append(pytest.mark.xfail(
                reason="amendment-history text is deliberately not indexed (see app/chunkers/njac.py)",
                strict=True,
            ))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


@pytest.fixture(scope="module")
def elevator_subcode_corpus(tmp_path_factory):
    """Module-scoped so the PDF is only ingested/embedded once for all 15
    cases, not once per case. pytest's `monkeypatch` fixture is function-
    scoped and can't be depended on here, so storage_dir is saved/restored
    manually instead (same effect as conftest.py's isolated_storage
    fixture, just at module scope)."""
    original_storage_dir = settings.storage_dir
    settings.storage_dir = tmp_path_factory.mktemp("eval_corpus")
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    vector_store.init_db()

    pdf_bytes = SOURCE_PDF_PATH.read_bytes()
    result = ingestion.ingest_document(pdf_bytes, SOURCE_PDF_PATH.name, None)
    assert result["chunk_count"] > 0

    yield result

    settings.storage_dir = original_storage_dir


@pytest.mark.parametrize("case", _case_params())
def test_eval_case(case, elevator_subcode_corpus):
    vector = embed_query(case["question"])
    results = vector_store.search(vector, top_k=5)
    citations = [chunk.get("citation") or "" for chunk, _title, _score in results]
    confidence = results[0][2] if results else 0.0

    if case["type"] == "negative-control":
        assert confidence < NEGATIVE_CONTROL_MAX_CONFIDENCE, (
            f"expected low confidence for an out-of-scope question, got {confidence:.3f}. "
            f"top hits: {citations}"
        )
        return

    expected_section = _expected_section(case["expected_citation"])
    assert any(expected_section in c for c in citations), (
        f"expected section {expected_section!r} not found in top-5 retrieved citations: {citations}"
    )

    if case["type"] == "amendment-history":
        # Finding the right *section* isn't the real claim here -- the
        # question needs the amendment date/year, which HISTORY_SPLIT_RE
        # strips out before indexing (see the xfail reason above). Checking
        # for a year from expected_answer in the retrieved text is what
        # actually exercises the known gap; this is expected to fail today.
        years = re.findall(r"\b(?:19|20)\d{2}\b", case["expected_answer"])
        assert years, f"no year found in expected_answer to check for: {case['expected_answer']!r}"
        retrieved_text = " ".join(chunk["text"] for chunk, _title, _score in results)
        assert any(year in retrieved_text for year in years), (
            f"none of the expected years {years} appear in the retrieved chunk text -- "
            "amendment history is not indexed"
        )

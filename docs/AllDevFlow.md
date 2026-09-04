# AllDevFlow — Construction RAG App: Development Log & Architecture Reference

This is the single running record of what this project is, why it's built the way it is, and
what's been done so far. It's meant to be read start-to-finish by someone (including a future
instance of Claude) picking this project up cold. Update it as work progresses — don't let it
drift out of sync with the code.

Original scope came from `dream.md` (project root): a RAG application over engineering/
construction documents — upload, chunk, embed, retrieve, answer with citations, via a React UI.
This log tracks how that plan evolved as it met real documents and real constraints.

---

## Status at a glance

*(Updated 2026-09-04 — see `PLAN.md` for the flat, fast-scan checklist this table summarizes;
this file stays the narrative/rationale companion to it, per the note at the top of this doc.)*

| Phase (per dream.md) | Status |
|---|---|
| Phase 0 — Source docs + chunking strategy sketch | ✅ Done |
| Phase 1 — Core backend (FastAPI, PDF parsing, chunking, embeddings, FAISS, `/query`) | ✅ Done |
| Phase 2 — OCR + CAD/GIS support | ✅ Done |
| Phase 3 — Citations + confidence refinement | ✅ Done |
| Phase 4 — React UI | ✅ Done, except a visual/design QA pass (layout, responsiveness, dark mode) |
| Phase 5 — Scaling + cloud | Not started |

Substantial work also happened outside dream.md's phase list entirely — document versioning, a
pluggable LLM provider switch, an async upload pipeline, and a full test/CI setup. See "Beyond
dream.md scope" below, in the order it was built.

---

## Phase 0 — Source documents & chunking strategy (done)

### What exists

- `NJ/links.md` — all links scraped from the NJ DCA "Codes & Regs" page
  (nj.gov/dca/codes/codreg/current.shtml). **Updated 2026-09-04** with a second scrape of
  `ucc.shtml` (the actual N.J.A.C. 5:23 subchapter index — see "Resolved 2026-09-04 — corpus is
  now complete" a few sections below, under Phase 1's "Final ingestion results", for why
  `current.shtml` alone wasn't enough).
- `NJ/pdfs/` — NJ regulation PDFs (public government publications, legally redistributable).
  7 downloaded directly; the remaining individual NJAC subchapter files were manually added
  later (see "Resolved 2026-09-04" below for the two added that day). 18 files total on disk as
  of Phase 1 completion — see "Final ingestion results" below for which ones are actually
  indexed; 20 files as of 2026-09-04.
- **Deliberately NOT downloaded**: IBC/IRC/IECC/IMC/IFGC (ICC), the base NEC (NFPA), the
  National Standard Plumbing Code (IAPMO), ASHRAE 90.1. NJ adopts these *by reference* but they
  are copyrighted publications distributed through the standards bodies' own licensed platforms,
  not NJ-hosted files. If/when the app needs their actual text, that requires a licensed
  subscription/export from the publisher — not scraping.
- `NJ/eval/chunking_strategy.md` — the chunking design, written after reading the actual
  `njac_5_23_12.pdf` structure rather than guessing.
- `NJ/eval/eval_set.json` — 15 hand-verified Q&A cases (incl. 2 negative controls) against
  `njac_5_23_12.pdf`, used to sanity-check retrieval + generation quality.
- `NJ/eval/chunk_prototype.py` — throwaway prototype chunker (superseded by
  `backend/app/chunkers/njac.py`, see below).

### Key discovery that shaped everything downstream

NJAC regulation PDFs are **not prose documents**. Reading the real file (not guessing) showed:
- Every section (`§ 5:23-12.X <Title>`) is a clean, pre-structured unit: lettered subsections
  `(a)(b)(c)`, nested numbers `1. 2. 3.`, nested romanettes `i. ii. iii.`.
- Every section ends with a long `HISTORY:` amendment log + `Annotations/Notes` boilerplate +
  copyright footer — low retrieval signal, but sometimes the actual answer to "when was this
  amended."
- §12.6 has real fee tables that a naive sentence-chunker would flatten into unreadable text.
- **The header/breadcrumb/citation block repeats on every PDF page**, not just the first page of
  a section. Splitting on `§ 5:23-12.X` headings alone fragments one section into N pieces (one
  per page it spans). The only marker that appears exactly once per true section is
  `End of Document`. This bug was caught by actually running the prototype against the real file
  and eyeballing output — see the "Bug found & fixed" note in `NJ/eval/chunk_prototype.py`'s
  docstring for the full story. **Lesson for future ingestion work on any new document source**:
  always dry-run the chunker against one real file and inspect actual chunk boundaries before
  trusting a structural assumption.

This is why the chunking strategy is **structure-aware and document-type-specific**, not the
generic 200-500-word sentence chunker originally sketched in `dream.md` section 2. See
`NJ/eval/chunking_strategy.md` for the full rationale.

---

## Phase 1 — Core backend

### Scope actually built (vs. dream.md's original Phase 1 list)

dream.md listed: FastAPI setup, PDF parsing, chunking, embeddings, FAISS index, basic `/query`
endpoint. Built as:

- `POST /upload` — accepts a PDF, extracts text, chunks it, embeds chunks, stores vectors +
  metadata. Runs **synchronously** in the request handler (see Known Limitations below).
- `GET /documents` — lists ingested documents with chunk counts.
- `GET /documents/{doc_id}/chunks` — returns all chunks for a document (added beyond the
  original spec — directly supports the "chunk preview" UI requirement from dream.md section 6.2
  and made debugging the chunker enormously easier during development).
- `POST /query` — embeds the question, does FAISS top-k similarity search, returns matched
  chunks with citations and a similarity-based confidence score. **Optionally** synthesizes an
  LLM answer if `RAG_ANTHROPIC_API_KEY` is configured (see "LLM generation" below) — otherwise
  returns the raw retrieved passages so the retrieval path is fully testable without any paid API
  dependency.

### Architecture decisions & why

**Pluggable chunker registry, not one universal chunker.** `backend/app/ingestion.py` sniffs the
extracted text (`looks_like_njac()`) and routes to `backend/app/chunkers/njac.py` (structure-aware,
ported from the validated Phase-0 prototype, with the numbered-item recursive split added — see
"Gap closed" below) or `backend/app/chunkers/generic.py` (sentence-based ~300-400 word grouping,
the original dream.md-style fallback for non-NJAC engineering docs). This mirrors how real
ingestion pipelines work — format/content detection routes to a specialized parser, with a
generic fallback — and keeps the door open to add more specialized chunkers (e.g. a table-heavy
spec-sheet chunker) later without touching the generic path.

**Gap closed from Phase 0**: the throwaway prototype only implemented 2 of the 3 planned
recursion levels (whole-section, then lettered-subsection). `§12.3(a)` in the real document is
732 words with no further lettered subsections to split on — just numbered items. The production
chunker (`backend/app/chunkers/njac.py`) adds the third level: when a lettered subsection is
still oversized, it splits on numbered items `1. 2. 3.`, grouping consecutive short items
together (up to the word cap) rather than exploding into one chunk per item.

**Local embeddings (sentence-transformers `all-MiniLM-L6-v2`), not an OpenAI API.** Per the
privacy/cost tradeoff flagged during initial planning review: no API key required, works offline
after the first model download, zero marginal cost per document. The NJ regulation PDFs used for
Phase-1 testing are public, but later phases may ingest proprietary engineering notes, and
defaulting to local keeps that decision from being made by default/accident. Swappable later:
`backend/app/embeddings.py` is the only module that would need to change (`embed_texts` /
`embed_query` are the entire interface other modules depend on).

**FAISS (`IndexFlatIP` on normalized vectors = cosine similarity) + SQLite for metadata.**
Matches dream.md section 3.2 exactly. FAISS row ids are assigned sequentially as vectors are
added; SQLite's `chunks.faiss_row_id` column maps a search hit back to full chunk metadata
(citation, section title, source text, cross-references). See `backend/app/vector_store.py`.

**Citations are derived programmatically, not trusted from LLM output.** `/query` builds the
`citations` list directly from which chunks were actually retrieved (doc title + citation/page),
independent of whatever the LLM says. This was a specific concern raised during Phase-0 planning
review: LLM self-rated confidence/citation formatting is unreliable. Confidence score is the
top-1 cosine similarity from FAISS, not an LLM self-rating — same reasoning.

**LLM generation is optional and gracefully absent, not a hard dependency.** `backend/app/llm.py`
only calls the Anthropic API if `RAG_ANTHROPIC_API_KEY` is set (`.env`, see `.env.example`).
Without a key, `/query` still returns ranked chunks + programmatic citations + confidence —
useful and testable on its own. `answer` is `null` and `llm_used: false` in that case, so the API
consumer can tell the difference between "no answer" and "answer not attempted."

### Setup & running

```powershell
# one-time setup (already done in this environment)
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# run the API
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload

# optional: enable LLM answer synthesis
copy backend\.env.example backend\.env
# then edit backend\.env and set RAG_ANTHROPIC_API_KEY
```

API docs available at `http://127.0.0.1:8000/docs` (FastAPI auto-generated) once running.

### Verification performed

Ran the full loop end-to-end against the real `njac_5_23_12.pdf` (not a synthetic test file):

1. **Chunking, isolated** — `backend/tests/test_chunking.py` runs the chunker directly (no
   FastAPI/embeddings/FAISS needed). Confirmed 35 chunks produced, chunker auto-selected `njac`,
   and **zero chunks exceed the 500-word cap** — the level-3 recursive split (added to close the
   Phase-0 prototype gap) correctly breaks up `§12.3(a)` into 3 sub-chunks instead of leaving one
   732-word chunk.
2. **Full pipeline via API** — started uvicorn, `POST /upload` with `njac_5_23_12.pdf`:
   `{"chunker_used":"njac","chunk_count":35}`, matching the isolated test exactly.
   `GET /documents/{doc_id}/chunks` returns all 35 chunks with correct citations/text.
3. **Retrieval quality**, using cases from `NJ/eval/eval_set.json` against the live `/query`
   endpoint (no LLM key configured, so this tests retrieval + confidence scoring specifically):

   | Question | Top retrieved citation | Expected | Confidence |
   |---|---|---|---|
   | Initial registration fee for an elevator device | `N.J.A.C. 5:23-12.5` | `5:23-12.5` ✅ | 0.82 |
   | Days a building can be open to qualify as a seasonal facility | `N.J.A.C. 5:23-12.10` | `5:23-12.10` ✅ | 0.67 |
   | Minimum accessible parking space width (negative control — not in this doc; it's in the barrier-free subcode, 5:23-7, not indexed) | `N.J.A.C. 5:23-12.12` (wrong, as expected) | N/A | **0.34** |

   The negative-control result is the interesting one: confidence for an out-of-scope question
   (0.34) is roughly half that of the two genuinely answerable questions (0.82, 0.67). This is a
   real, measured signal — not a guess — that a confidence threshold (e.g. "don't answer below
   ~0.4-0.5") is a viable, cheap way to catch out-of-scope questions before Phase 3's fuller
   confidence-scoring work, and it doesn't depend on an LLM self-rating anything.
4. **LLM synthesis path** — not exercised yet (no `RAG_ANTHROPIC_API_KEY` configured in this
   environment). Code path exists (`backend/app/llm.py`) and `llm_used: false` / `answer: null`
   was confirmed to come back correctly when unconfigured, rather than erroring.

**Generic chunker path** — later exercised for real against `52_27D_119.pdf` (the UCC Act itself,
318 chunks) and `nec_2023_tia_1_13.pdf` (27 chunks), both non-NJAC-structured documents that
correctly fell through to `generic_chunk()`. Confirmed working; not deeply inspected for chunk
quality beyond word-count bounds.

### Bug found during full-corpus ingestion: chunk_id collisions

Uploading the full `njac_5_23.pdf` (all 12 subchapters combined, 1088 chunks) plus several other
files hit `sqlite3.IntegrityError: UNIQUE constraint failed: chunks.chunk_id`. Root cause: chunk
IDs in `njac.py` are derived from citation text (e.g. `..._(a).1+`), and on a large enough
document, nested numbered lists within the same lettered subsection can restart at "1." (a
sub-list inside item 3 also starting at 1), producing two different numbered-item groups that
both resolve to the same citation string. SQLite correctly caught this rather than silently
overwriting a chunk.

**Fix**: added `_dedupe_chunk_ids()` to `backend/app/chunkers/njac.py` — a post-processing pass
that appends `#2`, `#3`, etc. to any chunk_id collision, guaranteeing uniqueness by construction
instead of trusting citation text to never repeat. Because the failed uploads had already written
vectors into the FAISS index before their SQLite transaction rolled back (FAISS writes aren't
transactional the way SQLite is), fixing this required a full reset (`rm -rf backend/storage/`)
and re-ingesting everything from scratch rather than patching in place. Verified: `njac_5_23.pdf`
re-ingests cleanly at 1088 chunks, no collisions.

### Decision: exclude the full combined UCC document from the index

Once individual NJAC subchapter files (`njac_5_23_1.pdf` ... `njac_5_23_12.pdf`) were added to
`NJ/pdfs/` alongside the full `njac_5_23.pdf`, the same content would be indexed twice — once as
part of the 1088-chunk combined document, once again per-subchapter. Rather than assume which was
preferred, this was raised explicitly; decision: **index only the individual subchapter files,
exclude `njac_5_23.pdf`**. Per-subchapter files give cleaner, more specific citations (a query
about elevators cites `njac_5_23_12.pdf` directly rather than a combined document spanning all 12
subchapters) with no duplicate content. Required another full reset + re-ingest cycle to remove
the combined document's 1088 chunks and replace them with the per-subchapter equivalents.

### Final ingestion results (Phase 1 close-out)

**Superseded by Phase 2** — the 4 "needs OCR" entries below turned out to be misdiagnosed (see
Phase 2's "The bigger discovery" section); 3 of them just needed a chunker regex fix, not OCR, and
the 4th is a legitimately-empty reserved subchapter. Current state is 17/18 indexed (see Phase 2's
verification section for the up-to-date table). Left as-is below for the historical record of what
Phase 1 actually shipped with.

Of 18 PDFs present in `NJ/pdfs/`, **13 are indexed**, 1 is deliberately excluded, and 4 cannot be
processed yet:

| File | Result | Chunks |
|---|---|---|
| njac_5_23_1.pdf | ✅ njac | 12 |
| njac_5_23_2.pdf | ✅ njac | 129 |
| njac_5_23_3.pdf | ✅ njac | 128 |
| njac_5_23_4.pdf | ✅ njac | 133 |
| njac_5_23_5.pdf | ✅ njac | 85 |
| njac_5_23_6.pdf | ✅ njac | 406 |
| njac_5_23_7.pdf | ✅ njac | 36 |
| njac_5_23_8.pdf | ✅ njac | 87 |
| njac_5_23_9.pdf | ✅ njac | 20 |
| njac_5_23_11.pdf | ✅ njac | 8 |
| njac_5_23_12.pdf | ✅ njac | 35 |
| 52_27D_119.pdf | ✅ generic | 318 |
| nec_2023_tia_1_13.pdf | ✅ generic | 27 |
| **Total indexed** | | **1424** |
| njac_5_23.pdf | ⛔ excluded (duplicate content, see decision above) | — |
| njac_5_23_3A.pdf | ❌ no extractable text (scanned image, needs OCR) | — |
| njac_5_23_4A.pdf | ❌ no extractable text (scanned image, needs OCR) | — |
| njac_5_23_4B_C.pdf | ❌ no extractable text (scanned image, needs OCR) | — |
| njac_5_23_4D.pdf | ❌ no extractable text (scanned image, needs OCR) | — |

The 4 OCR failures are handled cleanly (`ingestion.py` raises a clear 4xx-style error —
`"No extractable text found in PDF (may need OCR — not implemented in Phase 1)"` — rather than
crashing or silently indexing nothing). Decision: leave these for Phase 2 rather than rush an OCR
fallback into Phase 1; will be revisited as part of the planned OCR work below.

**Resolved 2026-09-04 — corpus is now complete.** This note originally flagged that subchapter 10
wasn't present and that the manually-copied files hadn't been checked against an authoritative
source list. Investigated properly: `NJ/links.md` (scraped from `current.shtml`) turned out to be
a narrower "external code cross-reference" page — it only lists subchapters that adopt an outside
I-Code (3, 6, 7, 12), not a table of contents. The actual subchapter index is
`https://www.nj.gov/dca/codes/codreg/ucc.shtml` (itself linked from `NJ/links.md`), which lists
all 17 N.J.A.C. 5:23 subchapters by number and title. Checked every one against `NJ/pdfs/`: the
user manually downloaded the two that were missing —
`njac_5_23_10.pdf` (Radon Hazard Subcode) and `njac_5_23_12A.pdf` (Optional Elevator Inspection
Program) — and all 17 are now present, matching the authoritative listing exactly:

| # | Title | Present |
|---|---|---|
| 1 | General Provisions | ✅ |
| 2 | Administration and Enforcement; Process | ✅ |
| 3 | Subcodes (Building/Plumbing/Electrical/Energy/Mechanical/1&2-Family/Fuel Gas) | ✅ |
| 3A | State-Jurisdiction Subcodes | ✅ |
| 4 | Enforcing Agencies; Duties; Powers; Procedures | ✅ |
| 4A | Industrialized/Modular Buildings and Building Components | ✅ |
| 4B & C | (Reserved) | ✅ |
| 4D | Recreational Park Trailers | ✅ |
| 5 | Licensing of Code Enforcement Officials | ✅ |
| 6 | Rehabilitation Subcode | ✅ |
| 7 | Barrier Free Subcode | ✅ |
| 8 | Asbestos Hazard Abatement Subcode | ✅ |
| 9 | Code Interpretations | ✅ |
| 10 | Radon Hazard Subcode | ✅ (added 2026-09-04) |
| 11 | Playground Safety Subcode | ✅ |
| 12 | Elevator Safety Subcode | ✅ |
| 12A | Optional Elevator Inspection Program | ✅ (added 2026-09-04) |

Both new files ingested via the live `/upload` API (35 and 18 chunks respectively, both correctly
`njac`-chunked) — no re-ingest of the rest of the corpus needed, since adding a document doesn't
affect existing ones. Corpus is now **19 documents, 2,108 chunks** (up from the 17/2,055 baseline
set by this session's chunking-fix re-ingest — see "Beyond dream.md scope" below for that work).

**Scope check, also 2026-09-04: N.J.A.C. 5:21 (Residential Site Improvement Standards / RSIS) is
explicitly out of scope, by user decision.** Asked whether it's part of the project — it isn't:
`dream.md` never named a specific regulation set, and this project's corpus scope was always
N.J.A.C. **5:23** (the Uniform Construction Code) specifically, established in this Phase-0
section above. 5:21 is a different NJAC chapter (also DCA-administered) covering subdivision/site
design standards (streets, parking, stormwater, utilities) for residential development, not
building construction — a different regulatory domain from everything indexed so far. Noting this
explicitly, same as Phase 0's "Deliberately NOT downloaded" IBC/IRC/etc. list above, so it isn't
mistaken for an oversight later: **not planned, not started, skip unless someone asks for it.**

### Known limitations / backlog (carried from Phase-0 planning review + new ones found while building)

- **Synchronous `/upload`.** PDF parsing + embedding can take seconds; a production version
  should push this to a background job (Celery/RQ) with a status-polling endpoint, matching the
  "show processing stages" UI requirement in dream.md section 6.1.A. Deferred because Phase 1's
  goal was a working core loop, not production hardening.
  **Resolved** — see "Beyond dream.md scope — `/upload` moved to an async background job" below
  (ended up using FastAPI `BackgroundTasks` rather than Celery/RQ; no separate broker needed at
  this scale).
- **No document versioning.** Re-uploading a revised PDF creates a new `doc_id` with its own
  chunks; old chunks aren't superseded. Construction docs get revised via addenda constantly —
  this needs a real decision (replace-on-reupload vs. version-tag + "latest" filter) before
  Phase 2.
  **Resolved** — see Phase 2's "Document versioning" section below.
- **No eval automation yet.** `NJ/eval/eval_set.json` exists but nothing runs it against the
  live `/query` endpoint automatically. Worth a small script before iterating further on
  chunking/retrieval quality, so regressions are caught rather than eyeballed.
  **Resolved** — see "Beyond dream.md scope — eval-set runner wired up as a regression test"
  below.
- **Generic chunker's sentence splitter is regex-based, not NLTK/spaCy.** Chosen to avoid a
  runtime model-download dependency for Phase 1. Fine for straightforward paragraph prose; revisit
  if real engineering-note documents (Phase 2 CAD/GIS exports) show poor sentence boundaries.
- **No OCR path yet.** dream.md Phase 2 scope (Tesseract/Azure Vision for scanned drawings) not
  started. Flagged in original planning review as a real risk area (technical drawings/dimension
  callouts) — worth testing against real scanned samples early in Phase 2, not assumed to "just
  work." Now backed by 4 concrete real-world failing samples (`njac_5_23_3A.pdf`, `4A.pdf`,
  `4B_C.pdf`, `4D.pdf` — see "Final ingestion results" above); explicitly deferred to Phase 2
  rather than rushed into Phase 1. Use these same 4 files as the first OCR test set when Phase 2
  starts.
- **No auth, no multi-user, no rate limiting.** Explicitly out of scope until Phase 5 per
  dream.md's own timeline; noted here so it isn't mistaken for an oversight.

### Dev-environment note (not app scope, but worth recording)

Shell working directory persists across tool calls within a session. An early command
(`cd NJ/pdfs && ...` to download PDFs) left the shell's cwd inside `NJ/pdfs/` for later commands
that used relative paths (e.g. `mkdir -p docs backend/...`), creating stray empty directory trees
nested under `NJ/pdfs/`. No data was lost (every actual file write used an absolute path via the
Write tool, unaffected by shell cwd), but it's a reminder to always use absolute paths or an
explicit `cd` at the start of each shell command rather than relying on cwd state.

---

## Phase 2 — OCR + CAD/GIS support

### Scope built (vs. dream.md section 1.2/1.3 + timeline "Week 3")

dream.md listed: Tesseract/Azure Vision OCR for scanned images, DOCX/TXT support. Built:

- **DOCX/TXT ingestion** — `app/extractors.py` gained `extract_docx_pages()` (python-docx,
  whole document as a single "page" since python-docx has no reliable page-break API) and
  `extract_txt_pages()` (plain read). `ingestion.py` was generalized from `ingest_pdf()` to
  `ingest_document()`, dispatching on file extension (`SUPPORTED_EXTENSIONS = {.pdf, .docx, .txt}`
  in `extractors.py`). `upload.py` validates against that set instead of a hardcoded `.pdf` check.
- **OCR fallback for scanned PDFs** — `app/ocr.py`, using Tesseract (via `pytesseract`) for OCR
  and PyMuPDF (`fitz`) for page rasterization (pure pip wheel, no separate system dependency for
  rendering — only the Tesseract engine itself needs a system install). `extract_pdf_pages()` in
  `extractors.py` runs pdfplumber first as before, then OCRs only the specific pages that came
  back near-empty (`ocr.page_needs_ocr()`, threshold 20 chars) rather than every page of every
  PDF — a document that's 99% real text with one scanned page only pays OCR cost for that page.
  Tesseract chosen over a cloud OCR API for the same local-first/no-per-call-cost reasoning as the
  Phase 1 embeddings choice.
- Tesseract is a system binary, not pip-installable. `ocr.is_available()` checks for it at ingest
  time; if a page needs OCR and Tesseract isn't installed, the upload fails with a specific,
  actionable 422 (not a silent skip) — see "Known limitation" below, since this is the actual
  current state of this dev machine.

### The bigger discovery: the "needs OCR" diagnosis from Phase 1 was wrong

Phase 1 flagged 4 files (`njac_5_23_3A.pdf`, `4A.pdf`, `4B_C.pdf`, `4D.pdf`) as scanned/
image-only PDFs needing OCR, based solely on the generic error message
`"No extractable text found in PDF"`. Investigating properly before installing Tesseract (rather
than assuming the Phase 1 diagnosis was correct) found the real cause: **these files have
perfectly good extractable text** — `pdfplumber` pulled 766–38,955 characters per file, none of
it image-derived. The actual bug was in `njac_chunk()`'s section-heading regex:

```
SECTION_HEADING_RE = re.compile(r"^§\s*(5:23-\d+(?:\.\d+)?)\s+(.+)$", ...)
```

This only matches purely-numeric subchapter numbers (`5:23-12`). All 4 "failing" files have
**letter-suffixed subchapter numbers** — `5:23-3A`, `5:23-4A`, `5:23-4B`/`4C`, `5:23-4D` — so
`\d+` alone stopped matching partway through (e.g. "3A" → `\d+` consumes "3", then needs `\s+`
but the next character is "A", so the whole line fails to match). Zero section matches → zero
chunks → `ingest_pdf`'s generic `"No extractable text found"` fallback fired, which was
technically true (zero *chunks*) but a misleading description of *why*.

**Fix**: `SUBCHAPTER_NUM_RE = r"5:23-\d+[A-Za-z]?(?:\.\d+)?"`, shared by `SECTION_HEADING_RE` and
`CROSSREF_RE` (which had the identical limitation for cross-reference extraction). Verified against
all 4 files directly (`SECTION_HEADING_RE.findall()` + `njac_chunk()` output) before touching the
running app:

| File | Before fix | After fix |
|---|---|---|
| njac_5_23_3A.pdf | 0 chunks | 2 chunks |
| njac_5_23_4A.pdf | 0 chunks | 27 chunks |
| njac_5_23_4D.pdf | 0 chunks | 9 chunks |
| njac_5_23_4B_C.pdf | 0 chunks | 0 chunks (see below — this one's different) |

`njac_5_23_4B_C.pdf` turned out to be a **genuinely reserved placeholder subchapter** — its only
content is "SUBCHAPTERS 4B AND 4C. (RESERVED)", no per-section heading at all, so no regex fix
could produce section chunks from it (there's nothing there to chunk). Rather than error on a
document that plainly has real, extractable, meaningful text (5 short lines saying "this is
reserved"), `ingestion.py` now falls back to the `generic` chunker whenever `njac_chunk()` returns
zero chunks despite `looks_like_njac()` matching — producing 1 chunk of that reserved-notice text,
which is arguably the *correct* answer to "what's in subchapter 4B?" (answer: nothing, it's
reserved) rather than a hard failure.

**Net effect: none of these 4 files needed OCR at all.** OCR support was still built (see above)
because it's real, useful Phase 2 scope for genuinely scanned documents in the future — but it
turned out to be solving a problem these specific 4 files didn't actually have. Lesson: an error
message like "no extractable text" describes a downstream *symptom* (zero chunks), not
necessarily the actual cause (could be zero raw text, or a chunker regex not matching real text) —
worth checking `pdfplumber` output directly before assuming which one it is.

### Verification performed

- Confirmed all 4 files produce correct chunks via direct chunker-module testing (bypassing the
  API) before touching the running app — see table above.
- Full clean re-ingest of all 17 non-full-UCC source files (same set as Phase 1's final ingestion,
  now including the 4 previously-failing ones) via the live `/upload` API:
  **17/17 documents succeeded, 1463 total chunks** (up from 13/17, 1424 chunks, in Phase 1).
  `njac_5_23_3A.pdf` → 2 chunks (njac), `4A.pdf` → 27 chunks (njac), `4B_C.pdf` → 1 chunk
  (generic fallback), `4D.pdf` → 9 chunks (njac).
- Retrieval-quality spot check against the newly-ingested 3A content via `/query`: a targeted
  question ("What is designated as the amusement ride subcode...") correctly surfaced
  `njac_5_23_3A.pdf — N.J.A.C. 5:23-3A.2` as the top citation (confidence 0.66). A vaguer phrasing
  of the same question ranked two `njac_5_23_3.pdf` chunks higher instead — expected embedding
  behavior given there are only 2 chunks about this narrow topic among 1463 total, not a chunking
  bug (confirmed by reading `njac_5_23_3A.pdf`'s chunks directly via
  `/documents/{doc_id}/chunks` — both chunks are clean and correctly citation-tagged).
- DOCX and TXT ingestion tested with small generated sample files (not real construction
  documents — none were on hand) via `/upload`: both correctly routed to the `generic` chunker
  and produced 1 chunk each.
- **OCR fallback verified end-to-end** after the user installed Tesseract (UB-Mannheim build,
  v5.5.3) manually per the plan above. Two gotchas found and fixed while verifying:
  1. `pytesseract` looks for `tesseract` on `PATH`, but a Windows installer updates the
     system/user `PATH` registry keys, which a shell (or backend process) already running when
     the installer runs won't see until a fresh login/session. `ocr.is_available()` now checks
     `shutil.which("tesseract")` first and falls back to the known UB-Mannheim default install
     path (`C:\Program Files\Tesseract-OCR\tesseract.exe`) if that's where the binary actually is
     — avoids requiring a machine restart or new terminal just to pick up the PATH change.
  2. No real scanned document exists in the current corpus (that was the whole point of the
     misdiagnosis correction above), so a synthetic image-only PDF was generated on the fly
     (Pillow, text drawn onto a blank image, saved as a PDF with no text layer) specifically to
     exercise the OCR path. Verified via `extractors.extract_pdf_pages()` directly
     (`ocr_status: "used"`, recovered text accurate aside from one letter-casing OCR artifact) and
     via a real `POST /upload` call (`"ocr_used": true` in the response). Test file deleted
     afterward and the index cleaned via another full wipe + re-ingest (17 real files, no synthetic
     test doc left behind).
- **DOCX/TXT tested only with tiny synthetic samples**, not real construction documents. No real
  DOCX/TXT engineering files were available in this project yet.
  <!-- todo -->
- **DOCX has no page-number metadata** (python-docx has no reliable page-break API) — the generic
  chunker's `page_number` field will be `None` for all DOCX-derived chunks, same as it already is
  for `njac_section`-type chunks. Acceptable for now (addenda/notes, not the huge regulation PDFs
  where page numbers matter more), but worth revisiting if DOCX becomes a primary source type.
- **CAD/GIS support** — dream.md's phrasing ("Treat exported PDF/TXT/DOCX as standard documents")
  is already satisfied by the 3 formats above; no CAD/GIS-specific parsing (e.g. DWG/DXF/shapefile)
  was in scope for dream.md itself, so none was built. Flagging here only so it isn't mistaken for
  an oversight if CAD-native files come up later.

### Duplicate-upload detection

Not in dream.md, but a real gap noticed during Phase 4 UI testing: uploading the same PDF twice
(confirmed via the user's own drag-and-drop testing, which produced two `njac_5_23_2.pdf` entries
in the document list) silently created two fully-duplicated documents with no warning. Added:

- `documents.content_hash` column (SQLite, indexed) — SHA-256 of the raw uploaded bytes.
- `vector_store.find_document_by_hash()` — checked in `ingestion.ingest_document()` **before**
  any file I/O, chunking, or embedding happens, so a duplicate is rejected cheaply, not after doing
  the (wasted) work.
- `DuplicateDocumentError` (a `ValueError` subclass carrying the existing doc's info) → `upload.py`
  returns **409 Conflict** with a message naming the existing `doc_id`/title, distinct from the
  existing 422 (unprocessable file) and 400 (unsupported type) cases. No frontend changes needed —
  `UploadComponent`'s error handling is already generic over any non-2xx status.
- Hash is of file **content**, not filename — catches the same file re-uploaded under a different
  name, and correctly does *not* flag two different files that happen to share a name.
- This required a schema change (`content_hash NOT NULL`), so — same pattern as every other schema
  change in this project — required a full `rm -rf backend/storage/` + re-ingest rather than a
  migration, since there's no migration tooling yet (noted as a gap, not fixed here).

**Verified**: uploaded `njac_5_23_11.pdf`, then uploaded the identical file again — first call
succeeded normally, second call returned `409 {"detail":"This file was already ingested as
'njac_5_23_11.pdf' (doc_id=e433b90ced3e)"}`.

**Known limitation**: this only catches byte-identical files, not semantic duplicates (e.g. the
full `njac_5_23.pdf` vs. its individual subchapter files — different bytes, overlapping content).
That's a much harder problem (content-level dedup) and was handled earlier via an explicit human
decision (exclude the full document), not automatically — out of scope for this hash-based check.

### Document deletion

Also not in dream.md, added when the user asked how to remove an uploaded document (e.g. to clean
up a duplicate or a test file). `DELETE /documents/{doc_id}` (`routers/documents.py`) →
`ingestion.delete_document()` → `vector_store.delete_document()`, plus a "Delete" button per row in
`DocumentList.tsx` (confirms via `window.confirm()` before calling the API).

- **The FAISS index is deliberately left alone on delete** — only the SQLite `documents` and
  `chunks` rows are removed, plus the raw file under `storage/documents/{doc_id}/`. `IndexFlatIP`
  row ids are positional; compacting the index after a delete would shift every subsequent row's
  id and silently break their `chunks.faiss_row_id` mappings. Instead, deleted chunks become
  "orphaned" FAISS rows with no matching SQLite row — `vector_store.search()` already tolerates
  this (skips a hit if its `faiss_row_id` doesn't resolve to a chunk), so a delete just means those
  rows can still be found by FAISS but never surface as results.
- **Known limitation**: the FAISS index only grows, never shrinks — deleting documents doesn't
  reclaim index space. Acceptable at this corpus size (thousands of vectors); would need a real
  compaction strategy (rebuild index + remap ids) if deletions become frequent at scale.
- **Verified**: used to clean up a synthetic OCR test document mid-session — `DELETE
  /documents/{doc_id}` returned `204`, the document disappeared from `GET /documents`, and the
  index was confirmed back to the real 17-document/1463-chunk corpus afterward.
- This still doesn't solve **document versioning** (re-uploading a revised file makes a new
  `doc_id` rather than superseding the old one) — see the dedicated section below.

### Document versioning

Carried as a known limitation since Phase 1: re-uploading a revised document just created a second,
unrelated `doc_id` with no link between them. Raised explicitly for a decision between two designs
— **replace-on-reupload** (delete the old version, no history) vs. **version-tag + keep history**
(keep every version, retrieval only searches the latest) — user chose the latter.

- `documents` gained `supersedes_doc_id` (nullable, points at the version it replaces) and
  `is_latest` (bool, default 1). `POST /upload` gained an optional `supersedes` form field naming
  the `doc_id` to replace; `ingestion.ingest_document()` validates that doc exists and is currently
  the latest version (a version chain is deliberately linear — you can't supersede an
  already-superseded version, you must replace whatever is *currently* latest) before ingesting the
  new file and flipping the old one's `is_latest` to 0. The old version's rows and FAISS vectors are
  **not deleted** — that's what makes this "history" rather than replace-on-reupload.
- `vector_store.search()` now skips any FAISS hit whose owning document isn't `is_latest` — same
  join-and-skip tolerance pattern already used for orphaned rows left by a deletion, so a superseded
  version's chunks stay in the FAISS index (harmless, same tradeoff as deletion) but never surface
  in retrieval.
- `GET /documents` defaults to latest-only; `?include_all=true` returns every version.
  `GET /documents/{doc_id}/versions` walks the `supersedes_doc_id` chain in both directions and
  returns the full history for whichever document you ask about, oldest first.
- Frontend: `DocumentList` gained a per-row "Replace" control (a file input, same hidden-input
  pattern as the main uploader) next to Delete, and a "Show superseded versions" checkbox that
  toggles `include_all` and renders older versions dimmed with a "superseded" badge.
- Required the schema change → full `rm -rf backend/storage/` + re-ingest cycle, same as every
  other schema change in this project (still no migration tooling).
- **Verified end-to-end**: uploaded a synthetic revised version of `njac_5_23_11.pdf` via
  `supersedes=<old doc_id>`; confirmed the old version disappeared from the default `/documents`
  list but still appeared under `?include_all=true` with `is_latest: false`; confirmed
  `/documents/{doc_id}/versions` returned both in order; confirmed `/query` for content unique to
  the new version retrieved only the new version's chunk, never the old one's. Cleaned up both test
  versions afterward and re-ingested the real `njac_5_23_11.pdf` to restore the 17-document/
  1463-chunk baseline.
- **Known limitation**: deleting the current latest version of a document doesn't auto-promote its
  predecessor back to latest — the chain just loses its head. Not handled, since it's an unusual
  action (you'd normally replace, not delete, the latest version) — flagged here rather than
  silently allowed to produce a confusing state.

---

## LLM provider switch (Anthropic / Ollama)

Not tied to a specific dream.md phase. Raised as a question ("can we use something other than an
Anthropic key?") while the `RAG_ANTHROPIC_API_KEY` requirement was still deferred; discussed
free-tier cloud options (OpenRouter, Gemini, Groq) and a fully-local option (Ollama). Ollama was
picked specifically to test the functionality without any API key or billing at all, and because it
matches the same local-first reasoning already used for `embeddings.py` (see Phase 1).

- `backend/app/llm.py` is the **only** module that talks to an LLM provider — `routers/query.py`
  and `routers/summary.py` only ever call `llm.is_configured()` / `llm.synthesize_answer()` /
  `llm.synthesize_summary()`, and don't know which provider is active. This meant adding a second
  provider touched exactly one backend module plus `config.py`; nothing in retrieval, chunking,
  storage, or the frontend needed to change.
- New setting: `RAG_LLM_PROVIDER=anthropic|ollama` (default `anthropic`, unchanged behavior).
  Ollama-specific settings: `RAG_OLLAMA_BASE_URL` (default `http://localhost:11434`),
  `RAG_OLLAMA_MODEL` (default `llama3.1`) — no API key needed for Ollama, since it's a local server
  process, not a cloud call. `RAG_OLLAMA_NUM_GPU` (optional; forwarded as `options.num_gpu` in the
  Ollama `/api/chat` request body) was added after the end-to-end verification below surfaced a
  real perf issue on this dev machine — see the note there. `_ollama_chat` also uses a 300s
  timeout (bumped up from Ollama's own 120s default, too short for CPU-only inference on an 8B
  model).
- Ollama calls use Python's stdlib `urllib.request` (raw HTTP POST to `/api/chat`), not a new pip
  dependency — the request/response shape is simple enough not to need an SDK.
- `is_configured()` now means different things per provider: for Anthropic it's still a static "is a
  key set" check; for Ollama it's a runtime reachability check (`GET /api/tags`, 1.5s timeout) —
  same reasoning as `ocr.is_available()` in Phase 2: a *configured* provider isn't the same as one
  that's actually *running* right now, and Ollama is a local server that may not be up.
- **Operational prerequisite** (not code): Ollama must be installed as a system binary and a model
  pulled locally (e.g. `ollama pull llama3.1`) before `RAG_LLM_PROVIDER=ollama` does anything —
  same category of external dependency as the Tesseract install in Phase 2.
- **Switching back to Anthropic (or between the two at all) is a config-only change** —
  `RAG_LLM_PROVIDER` + a restart, no code edit — by design, since both providers are kept behind the
  same switch rather than one replacing the other.
- **Verified**: backend restarted with the new code (no schema change, no re-ingest needed — this is
  fully orthogonal to storage); confirmed `/query` still returns `llm_used: false, answer: null`
  correctly with no provider configured (regression check against the existing no-key behavior).
- **Ollama path since exercised end-to-end**: Ollama was installed and a model pulled locally,
  and summary generation (see Phase 4's summary endpoint above) was validated against it for
  real — not just the unconfigured-503 path. This is also where `RAG_OLLAMA_NUM_GPU` came from:
  this dev machine's GPU (GTX 1060 3GB) can't meaningfully accelerate the 8B model, so
  `RAG_OLLAMA_NUM_GPU=0` (forcing CPU-only) is currently faster than automatic partial GPU
  offload — see `PLAN.md`'s backlog for this as an open, machine-specific limitation rather than
  a bug to fix in code.

---

## Phase 4 — React UI

### Scope actually built (vs. dream.md section 6)

dream.md specified 3 pages (Upload, Q&A, Summary) and 6 components. Built as a Vite + React +
TypeScript app under `frontend/`, no router library (only 3 pages, simple tab-switch state in
`App.tsx` was enough — avoided pulling in react-router for something this small):

- **Upload page** (`pages/UploadPage.tsx`) — `UploadComponent` (drag-and-drop + click-to-browse,
  per-file status: Queued → Processing… → Done/Error) + `DocumentList` (table of ingested docs,
  refetches after each successful upload).
- **Q&A page** (`pages/QAPage.tsx`) — `QuestionBox` (textarea + top-k input) → `AnswerCard`
  (answer text, confidence badge, LLM-used indicator) → `CitationList` → `ChunkResultList`
  (snippet + score per retrieved chunk, "View full chunk" opens `ChunkPreviewModal` with full
  text/metadata). `ChunkResultList` isn't in dream.md's component list (6.2) but was needed to
  actually display "chunk previews" plural, as required by 6.1.B — `ChunkPreviewModal` alone only
  covers the single-chunk detail view.
- **Summary page** (`pages/SummaryPage.tsx`) — document dropdown, "Generate Summary" button,
  summary text, "Download summary (.txt)" button (client-side Blob download, no backend
  round-trip needed for that part).

### Backend addition required: summary endpoint

dream.md's Summary page ("select document → Generate Summary") had no backing endpoint — Phase 1
only built `/upload`, `/documents`, `/documents/{doc_id}/chunks`, `/query`. Added
`POST /documents/{doc_id}/summary` (`backend/app/routers/summary.py`) and
`llm.synthesize_summary()` (`backend/app/llm.py`) to close that gap. Design notes:

- **503 if no LLM configured**, not a silent/empty summary — matches the existing pattern of
  `/query`'s `answer: null` when unconfigured, but summary has no non-LLM fallback (there's no
  "raw passages" equivalent for "summarize this document"), so a clear error is the only honest
  response.
- **Word-budget cap (`MAX_SUMMARY_WORDS = 6000`)** on the context sent to the LLM. Some ingested
  documents are large (`njac_5_23_6.pdf` = 406 chunks) and dumping every chunk into one LLM call
  isn't a sane single-request budget. Chunks are included in FAISS-insertion order (roughly
  document order) up to the cap; response reports `chunks_used`/`chunks_total`/`truncated` so the
  UI can tell the user the summary is partial rather than silently truncating. Not yet validated
  against a real API key — the logic is straightforward but untested end-to-end pending a
  configured `RAG_ANTHROPIC_API_KEY`.

### CORS

Added `CORSMiddleware` to `backend/app/main.py` scoped to the Vite dev server origins
(`localhost:5173` / `127.0.0.1:5173`) — needed since frontend and backend run as separate dev
servers on different ports.

### Verification performed

- `npx tsc --noEmit` — clean, no type errors.
- Backend restarted with `--reload` so future edits don't require manual restarts during Phase 4
  iteration.
- End-to-end upload flow verified working via direct browser automation (Chrome extension,
  connected mid-session after an initial "not connected" failure — retried once and it worked):
  navigated to `localhost:5173`, used the file input directly to attach `njac_5_23_11.pdf`,
  confirmed it went through the full pipeline (`Done — 8 chunks (njac)`) and appeared in the
  document list. This confirms `UploadComponent`'s upload logic, `DocumentList`'s refetch-on-
  upload, and the backend `/upload` + CORS path all work correctly end-to-end.
- Not yet visually screenshotted/reviewed page-by-page for layout/style issues — verification so
  far is functional (does the data flow work), not a design review.

### Known issue: click-to-browse doesn't open the file picker (user-reported)

Drag-and-drop onto the dropzone works. Clicking the dropzone to open the OS file picker does not,
per direct user testing in their own Chrome browser — confirmed NOT a backend/upload-logic bug
(the upload path itself was verified working via a direct programmatic file attach, see above).

Already tried: switched `UploadComponent` from a `div onClick={() => inputRef.current?.click()}`
pattern to the more standard `<label htmlFor>` + associated `<input id>` pattern (the more robust,
extension-resistant approach for click-to-browse), plus made the input visually-hidden via CSS
(clip-rect technique) rather than the `hidden` attribute. Did not resolve it.

Suspected causes, not yet confirmed: a browser extension (ad blocker/privacy tool) on the user's
machine intercepting synthetic-looking clicks on file inputs, or the native OS file dialog opening
behind the browser window rather than in front of it. Diagnostic steps handed to the user: check
taskbar/Alt+Tab for a hidden dialog window, try Incognito mode (most extensions disabled by
default), check DevTools console for errors on click.

**Revisited 2026-09-04, code-level inspection only — still unresolved.** Checked the current
`UploadComponent.tsx`/CSS for anything that could explain this at the code level, ruling out the
usual structural suspects: `label[for]` and `input#id` match correctly; computed styles show
`pointer-events: auto` on both the label and input (nothing set to `none`); `input.disabled` is
`false`; and `document.elementFromPoint()` at the dropzone's center confirms the label itself (not
some overlapping element) is what actually receives the click. No CSS/DOM bug found.

Tried an actual click via browser automation to see whether a file dialog opens at all --
**this was a mistake**: the automation tooling's own `file_upload` tool documentation explicitly
warns against clicking real file inputs, since any resulting native OS dialog is outside the
browser's DOM and isn't observable through page screenshots or `document.visibilityState` (tried
both; both were inconclusive/misleading -- `visibilityState` stayed `"hidden"` even after clicking
completely unrelated, dialog-free areas of the page, so it's apparently just a baseline property of
this remote browser environment, not a signal of anything). No lasting harm -- the tab remained
fully interactive and responsive to further clicks/navigation afterward -- but this means **browser
automation cannot confirm or deny this bug either way**; it can only be diagnosed in a real browser
session by a human who can actually see whether the OS file picker opens.

**Still deferred to backlog** — drag-and-drop is a fully working alternative upload path in the
meantime, so this doesn't block using the app. Next step, if picked up again, has to be the user
testing directly (the diagnostic steps above) rather than another automated attempt.
<!-- todo -->

### Known limitations / backlog (Phase 4)

- **Summary generation untested against a real LLM call** — no `RAG_ANTHROPIC_API_KEY` configured
  in this environment yet; the 503-when-unconfigured path is verified, the actual summarization
  quality/prompt is not.
  **Resolved** — validated end-to-end against a real local LLM (Ollama, see "Beyond dream.md
  scope — LLM provider switch" below), not just the unconfigured-503 path.
- **No visual/design QA pass yet** — pages render and the data flows correctly, but no one has
  reviewed spacing, responsiveness, or dark-mode behavior in a real browser session yet.
  Still open as of 2026-09-04 — only functional/behavioral verification has happened since
  (upload flow, replace flow, etc.), no dedicated visual pass.
  <!-- todo -->
- **Click-to-browse file picker bug** — see dedicated section above. Still open as of
  2026-09-04 — no further diagnostic info has come back from the user, and the code hasn't
  changed since the fix attempt described above didn't resolve it. `PLAN.md` checks off
  "Upload page (drag-and-drop + click-to-browse, ...)" as done, but that reflects the feature
  existing and drag-and-drop working, not confirmation that click-to-browse itself was fixed —
  don't read that checkbox as contradicting this section.
  <!-- todo -->

---

## Beyond dream.md scope — testing, CI, and operational hardening

Everything in this section falls outside dream.md's phase list. Ordered by when it landed (see
git log — each has its own commit from this point on, unlike Phases 0-4 above which were built
and squashed into a single initial commit before this repo's git history starts).

### PLAN.md progress checklist

Added `PLAN.md` at the project root: a flat checklist mirrored against dream.md's phases, plus
"beyond scope" and "known issues/backlog" sections. This file (`AllDevFlow.md`) stays the
narrative/rationale record; `PLAN.md` is the fast-scan companion for "what's left" without
reading prose. Keep both in sync going forward — `PLAN.md`'s own header says as much.

### Summary page loading state

Small UX gap: `SummaryPage`'s "Generate Summary" button gave no feedback while the LLM call was
in flight — the Q&A page already showed a loading message, but Summary generation (which can
take a couple of minutes on a CPU-backed local Ollama model) only had the button's own label as
feedback. Added a matching `"Generating summary… this can take a couple of minutes."` message,
gated on the same `loading` state.

### CI pipeline

Added `.github/workflows/ci.yml`, running on every push/PR to `master`:

- **Backend job** — installs Tesseract OCR (`apt-get install tesseract-ocr`) so the real-OCR test
  (see Phase 2's OCR verification above) runs in CI exactly as it does locally, not skipped/mocked
  — then `pip install -r requirements.txt` and `pytest tests/ -v`.
- **Frontend job** — `npm ci`, `npm test` (Vitest), then `npm run build` (which runs `tsc -b`
  first per `package.json`'s build script, so a type error fails CI the same as a broken build
  would).

Both jobs run independently (no dependency between them) so a backend-only or frontend-only
change gets fast feedback without waiting on the other stack.

### Backend and frontend automated test suites

Not previously documented here even though they existed from this repo's first commit. Current
state (2026-09-04): **82 backend pytest tests** (81 passing + 1 documented `xfail` — see the
eval-set section below for what that xfail is) and **43 frontend Vitest + React Testing Library
tests**.

- **Backend** (`backend/tests/`) — one file per router/module (chunkers, extractors including a
  real Tesseract OCR run rather than a mock, LLM provider switching with the provider mocked,
  `vector_store` internals) plus `test_integration.py` for full
  upload→list→query→summary→delete lifecycles that touch all four routers together, and
  `test_eval_set.py` (see below). `backend/tests/conftest.py`'s `isolated_storage` fixture points
  `settings.storage_dir` at a per-test `tmp_path` so tests never touch the real dev
  database/FAISS index.
- **Frontend** — one `.test.tsx` per component/page, mocking `../api` (`vi.mock`) so component
  tests don't depend on a running backend. Several of these tests exist specifically as
  regression tests for real stale-state UI bugs found while building/testing the app (not
  hypothetical edge cases) — e.g. `UploadComponent`'s per-batch entry list not resetting between
  upload batches, and (added 2026-09-04) `DocumentList`'s Replace action not waiting for its
  background job — see "The async `/upload` background job" below for that one.

### Eval-set runner wired up as a regression test

`NJ/eval/eval_set.json` (Phase 0's 15 hand-verified Q&A cases against `njac_5_23_12.pdf`,
including 2 negative controls — see Phase 0 above) existed from the very start of the project but
nothing ever ran it automatically; Phase 1's "Known limitations" section above flagged this
explicitly. Added `backend/tests/test_eval_set.py`, which:

- Ingests **only** `njac_5_23_12.pdf` into an isolated per-test corpus (matching the eval set's
  original single-document design) rather than running against the full multi-document production
  corpus, which gives noisier/less meaningful results — a question written to test one specific
  document's retrieval shouldn't be scored against unrelated documents diluting the top-k.
- Runs all 15 cases through the live `/query` path and asserts against the expected
  citation/confidence behavior.

This surfaced two genuine findings — the eval set had simply never run before to catch them:

1. **The amendment-history case (q15) is a documented `xfail`, not a pass/fail toggle.** Section
   retrieval correctly finds `5:23-12.5`, but the actual answer (the 2014 amendment date/fee
   change) isn't retrievable, because `njac.py`'s `HISTORY_SPLIT_RE` deliberately strips each
   section's `HISTORY:` block before indexing (see Phase 0's chunking discovery above — that
   block was identified early on as "low retrieval signal, but sometimes the actual answer").
   Fixing this for real means `njac.py` stops discarding that block outright — store it as
   separate low-priority chunks or metadata instead of dropping it — tracked in `PLAN.md`'s
   backlog, not fixed here.
   **Resolved 2026-09-04** — see "Amendment-history indexing" below; q15's `xfail` is gone, it's
   a real pass now.
2. **The negative-control confidence threshold doesn't hold as tightly under re-measurement.**
   Phase 1's original verification (see above) measured one negative control at 0.34, well below
   genuine matches (0.82, 0.67), and floated "~0.4-0.5" as a viable don't-answer threshold. Running
   both negative controls now, one scores 0.58 — still comfortably below genuine matches
   (0.62-0.84) but above that originally suggested cutoff. The test uses a looser 0.65 bound
   rather than the original ~0.4-0.5 guess. This is a useful correction: the original number was a
   single measurement from one negative control, not a validated threshold, and re-measuring
   against both showed real variance.

**Also surfaced a corpus-drift bug while first running this test against live storage**: a
duplicate `njac_5_23.pdf` (the full combined UCC document, 1141 chunks) was sitting in the live
dev corpus even though Phase 1's "Decision: exclude the full combined UCC document from the
index" (above) explicitly excluded it. Root cause not investigated further (most likely
re-added during some later manual re-ingest cycle after one of the schema-change resets), but the
fix was straightforward: deleted it via `DELETE /documents/{doc_id}`, restoring the documented
17-document/1463-chunk baseline from Phase 2's close-out. Worth remembering next time a full
`rm -rf backend/storage/` + re-ingest happens: re-ingest from the same 17-file set Phase 2
verified against, not from a different file listing that happens to include the excluded
combined document.

### Configurable default Top-K

`QuestionBox.tsx` hardcoded `top_k=5` for every query. Added `VITE_DEFAULT_TOP_K` to
`frontend/.env`, now defaulting to 3. Reasoning: a higher top-k means a longer context block sent
to the LLM, and CPU-backed Ollama queries (see "LLM provider switch" above, and the GPU note in
`PLAN.md`'s backlog — this dev machine's GTX 1060 3GB can't meaningfully accelerate the 8B model)
could already take on the order of minutes at top-k=5; defaulting lower keeps the common case
faster without removing the option to raise it.

### `/upload` moved to an async background job

The single biggest item carried in Phase 1's "Known limitations" since the start of this log:
`/upload` ran the full extract/chunk/embed/store pipeline inline in the request handler, blocking
the connection for as long as that took (seconds to minutes for large documents). Fixed by
moving the slow part into a FastAPI `BackgroundTask` rather than reaching for an external queue
(Celery/RQ, as Phase 1's note had originally guessed) — at this project's single-process,
single-machine scale, FastAPI's built-in background-task mechanism (which runs a sync task via
its threadpool, off the event loop) is enough, and avoids a Redis/broker dependency.

- **Router split**: `POST /upload` now does only the cheap synchronous checks —
  `ingestion.validate_upload()` (duplicate-hash lookup, supersedes-target existence/is-latest
  validation, factored out of what used to be the start of `ingest_document()`) — before
  returning `202 {job_id, status: "queued"}` immediately. Those checks stay synchronous
  deliberately: they're cheap (a couple of DB lookups, no file parsing), so rejecting a bad
  request immediately with 409/422 is better UX than making the caller poll a job just to learn
  it failed validation.
- **`jobs` table** (new, in `vector_store.py`'s schema) tracks `status`
  (`queued`/`processing`/`done`/`error`), the eventual `result` (the same shape `/upload` used to
  return directly) or `error` message, keyed by `job_id`. `GET /upload/jobs/{job_id}` polls it.
- **Frontend**: `UploadComponent` now polls the job endpoint (800ms interval, via a new
  `pollJobUntilDone()` helper) and shows a `Processing…` state between "Uploading…" and
  "Done"/"Error".
- **Tests**: all backend tests that upload a document through the HTTP layer (not just
  `test_upload.py` — `test_documents.py`, `test_query.py`, `test_summary.py`,
  `test_integration.py` all had inline `client.post("/upload", ...)` calls asserting a synchronous
  200) were updated to use a new `conftest.py` helper, `upload_and_wait()`, which POSTs, then GETs
  the job status and returns its result. No polling loop needed in tests: Starlette's `TestClient`
  runs `BackgroundTasks` to completion as part of handling the request, so the job is already
  done/errored by the time `client.post()` returns.
- **Verified** against a real running server (`RAG_STORAGE_DIR` pointed at an isolated temp
  directory, not the dev corpus): `POST /upload` returned instantly with `status: "queued"`,
  polling showed the transition through `processing` to `done` with the full ingestion result.

**Bug found immediately after, via manual UI testing**: `DocumentList.tsx`'s "Replace" action
(added in Phase 2's "Document versioning" work) still awaited `uploadDocument()` as if it
resolved with the finished ingestion result — a leftover from before this change. Since
`uploadDocument()` now resolves immediately with `{job_id, status: "queued"}`, Replace was
refreshing the document list right after the job was *enqueued*, before the background task had
actually superseded the old document — the swap (old doc's `is_latest` flipping to 0, new doc
appearing) hadn't necessarily happened yet by the time the UI showed "done." Fixed by factoring
`pollJobUntilDone()` out of `UploadComponent` into a shared `frontend/src/uploadJob.ts` and having
`handleReplace()` await it too, only refreshing (or showing a "Replace failed" message) once the
job actually resolves. Two new tests added to `DocumentList.test.tsx` covering the success and
job-error paths — neither existed before this bug was found, since the original synchronous
`/upload` made a real "still pending" state impossible to observe.

**Verified manually end-to-end via direct browser automation**, against isolated storage (not the
dev corpus): uploaded a document, replaced it with a second file, confirmed the row updated to
the new file and the "Processing…" state was visible during the job; checked "Show superseded
versions" and confirmed the old version showed the `superseded` badge with no Replace action;
attempted a second Replace with duplicate content and confirmed a red "Replace failed: This file
was already ingested as ..." message appeared with the table correctly left unchanged (no
premature refresh — the exact bug just fixed). All test documents deleted and both servers torn
down afterward.

### A real retrieval miss, found via manual Q&A testing on the live dev corpus

The user asked the running app (real dev corpus, not a test fixture) *"Any special requirement to
build a fence around the property?"* and got back *"Not enough information."* The immediate
question was whether that's correct — the corpus genuinely lacking fence content — or a retrieval
bug. Investigated by inspecting what `/query` actually retrieved, not just trusting the answer
text:

- Grepped every live chunk's text directly (`SELECT ... WHERE lower(text) LIKE '%fence%'`) and
  found the corpus **does** have a directly relevant provision: `N.J.A.C. 5:23-2.14(b)` item 9,
  "A permit shall not be required for fences six feet or less in height. This exception does not
  apply to barriers surrounding public or private swimming pools." So this was a retrieval miss,
  not a corpus gap.
- That chunk didn't even appear in the top 9 of a `top_k=20` request (which itself only returned
  9 results — see below). Inspected the chunk directly: it was `5:23-2.14(b).5+`, a 472-word chunk
  bundling **five unrelated** permit exemptions (gas-utility metering, signs, lead abatement,
  utility sheds, *and* fences — items 5 through 9) into one embedding. The fence sentence is ~30
  of those 472 words; averaging its embedding with four unrelated topics diluted it enough that an
  unrelated-but-narrowly-focused chunk (an outdoor-maze permit exemption, sharing surface language
  like "height" and "permit") outscored it.
- **Root cause**: `_chunk_lettered_piece`'s numbered-item grouping (Phase 1 above) grows a group
  of consecutive numbered items up to the 500-word cap regardless of whether those items are
  topically related. That heuristic was designed and validated against one specific real case —
  §12.8(b)'s 33 "minor work" items (`NJ/eval/chunking_strategy.md` section 4.2), which *are*
  topically homogeneous and individually tiny ("Addition of rope equalizers" — genuinely
  context-free alone). Applying the same heuristic to `5:23-2.14(b)`'s list — which is
  topically *heterogeneous*, each item a complete independent provision — actively hurt retrieval
  instead of helping it. The original design reasoning was sound for the case it was built
  against; it just didn't generalize to every numbered list in the corpus, and nothing before now
  had surfaced a concrete failure to reveal that.
- **Fix**: added `MIN_GROUP_WORDS = 20` (`app/chunkers/njac.py`) — a numbered item at or above
  that size closes its own chunk rather than continuing to absorb whatever comes next; only items
  smaller than that (the "Addition of rope equalizers" case this grouping was actually built for)
  still merge with their neighbors. `MAX_CHUNK_WORDS` (500) is unchanged as the upper safety cap.
- **A second, more serious bug found while fixing the first**: `_split_on()` (shared by both the
  lettered-subsection split and the numbered-item split) silently **dropped any text before its
  first regex match**. Checked whether this was just a synthetic-test artifact or real: it is
  real. `njac_5_23_2.pdf`'s actual source text for `5:23-2.14(b)` reads *"(b) The following are
  exceptions from (a) above:\n1. Ordinary maintenance..."* — but the live chunk
  `N.J.A.C. 5:23-2.14(b).1+` started directly at "1. Ordinary maintenance...", missing that intro
  sentence entirely. This wasn't specific to this one section — it affects every lettered piece or
  section that has any intro text before its first numbered item or first lettered subsection,
  likely dozens of places across the corpus, and has been silently losing content since Phase 1.
  Fixed: `_split_on()` now keeps text before the first match as a leading piece instead of
  discarding it; `_chunk_lettered_piece`'s `flush()` was also fixed to scan the whole group for the
  first real numbered item when deriving a chunk's citation number (it used to assume `group[0]`
  was always a numbered item, which broke once a leading intro piece could be `group[0]`).
- **Also surfaced, investigating why `top_k=20` only returned 9 results**: the dev corpus's FAISS
  index held **3,035 vectors for only 1,463 live chunks** — 52% orphaned, accumulated from every
  past delete/supersede/schema-reset re-ingest cycle (the tradeoff documented, and deferred, in
  `delete_document()`'s docstring in Phase 2 above). `vector_store.search()` silently drops any
  FAISS hit that doesn't resolve to a live chunk, so a request for the top 20 nearest neighbors
  can — and did — return far fewer once roughly half of them turn out to be dead rows. This was
  quietly shrinking the effective top_k of *every* query, not just this one. Added
  `vector_store.compact_index()` + `backend/scripts/compact_faiss_index.py`: rebuilds the index
  from only live chunks, reconstructing each vector directly from the existing flat index (FAISS's
  `IndexFlatIP.reconstruct()` — no re-embedding needed) and reassigning sequential row ids. Writes
  to a temp file and swaps it in with `os.replace()` only after the SQLite row-id updates commit,
  so the existing (larger but valid) index stays intact for as long as possible if anything goes
  wrong partway through. Intended to run offline, backend stopped — not exposed as an HTTP
  endpoint, since this is a maintenance operation, not something a request should trigger.
- **Applied both chunking fixes to the live dev corpus**: backed up `backend/storage/` first, then
  did the usual full wipe + re-ingest of the same 17-file baseline (see Phase 1's "Final ingestion
  results" and Phase 2's close-out above) — same established pattern this project has used for
  every prior schema/logic change, since there's still no migration tooling. Result: **1,463 →
  2,055 chunks** (finer-grained, as expected from no longer over-merging heterogeneous items), and
  since it's a fresh index, `compact_index()` wasn't needed this time — 0 orphaned vectors by
  construction. `compact_index()` remains available for the next time deletes/supersedes
  accumulate orphans without a full re-ingest.
- **Verified the fix against the original failing question**: re-ran *"Any special requirement to
  build a fence around the property?"* against the live (re-ingested) corpus. The fence provision
  (`N.J.A.C. 5:23-2.14(b).9`, now its own chunk) scored 0.567 and was the **top** retrieved
  result — previously it hadn't even placed in the top 9 of a top-20 request. The LLM's answer
  now correctly cites it: *"There is a reference to fences in section 9 of N.J.A.C. 5:23-2.14...
  a permit is not required for fences six feet or less in height, unless they surround a public
  or private swimming pool."*
- **Tests**: `test_chunkers.py` — replaced the old grouping test (which exercised exactly the
  behavior just proven harmful) with one confirming substantial items each get their own chunk,
  added one confirming genuinely tiny items still group together (the original, still-valid
  motivating case), and a regression test for `_split_on()`'s leading-text bug.
  `test_vector_store.py` — two new tests for `compact_index()` (drops a real orphan and keeps
  live chunks searchable; no-ops cleanly on an already-compact index). Full suite: 85 passed + 1
  xfailed (up from 82), all passing before the live corpus was touched.

### Amendment-history indexing

The eval-set finding above (q15's documented `xfail`) was picked up as its own piece of work:
`njac.py`'s `HISTORY_SPLIT_RE` discarded every section's `HISTORY:` block outright before
chunking — amendment dates, N.J.R. register citations, and the plain-English change description
(e.g. *"Amended by R.2014 d.149, effective October 6, 2014...Updated the fee amounts"*) were never
indexed at all, so a "when was this amended" question had no chance of a real answer regardless of
retrieval quality.

- **Design**: added `_chunk_history_text()`, indexing each section's history as its own chunk,
  `chunk_type: "njac_history"`, citation `N.J.A.C. {section} History` (or `History (N)` for
  sections whose history is too long for one chunk). Kept as a **separate** chunk from operative
  text rather than appended/merged into it — same reasoning as the fence-question fix above:
  merging unrelated content dilutes an embedding. A regulatory-text chunk shouldn't have its
  meaning diluted by decades of amendment-log dates, and a history chunk should be *entirely*
  history so a date/amendment query scores it highly without competing against substantive rule
  text in the same chunk.
- **Sizing**: most sections' history is short (median 114 words across the whole corpus) and fits
  in one chunk. A few are not — up to 1,901 words for `5:23-4.20` (the most-amended section found,
  spanning amendments from 1982 to a 2024 administrative correction). Unlike operative text,
  history has no lettered/numbered structure to split on, so oversized history is split the way
  the generic chunker splits prose: `split_sentences()` (already used by `chunkers/generic.py`,
  reused here rather than duplicated) then grouped up to `MAX_CHUNK_WORDS`. `MIN_GROUP_WORDS`
  (the fix above) deliberately does **not** apply here: that constant exists to stop grouping
  *topically unrelated* items together, but consecutive amendment entries for the same section are
  all the same topic (this section's history), so dense grouping doesn't dilute anything the way
  it did for the numbered permit-exemption list.
- **A second bug found and fixed in the process**: every one of this corpus's 291 real sections
  ends with a trailing "Annotations / Notes / Chapter Notes / NEW JERSEY ADMINISTRATIVE CODE /
  Copyright..." footer (sometimes with genuine case-law commentary mixed in under "Case Notes" —
  left out of scope here, same reasoning as not downloading the base I-Codes: it's a different
  kind of content than the regulation text or its amendment history). This footer used to be
  silently swept into `operative_text` whenever a section had *no* History block to split it off
  first (the split only happens on a `HISTORY_SPLIT_RE` match) — **found live in 22
  already-ingested chunks** (e.g. `N.J.A.C. 5:23-1.2`, `5:23-2.1`, `5:23-12.7`), meaning this
  boilerplate had been polluting real indexed, retrievable content since Phase 1. Fixed with
  `ANNOTATIONS_FOOTER_RE`, stripped from both operative_text (unconditionally, since it's a no-op
  when a History split already removed it) and the new history chunks.
- **`test_eval_set.py` updated**: q15's `pytest.mark.xfail` removed — it now passes for real
  rather than being a stale pass/fail toggle nobody would notice flip. Three new
  `test_chunkers.py` tests: history indexed as a separate chunk, the Annotations-footer regression
  (a no-History section that used to leak boilerplate), and oversized-history splitting into
  multiple word-capped chunks.
- **Re-ingested the full 19-document corpus**: backed up `storage/` first (same pattern as the
  fence-question fix), full wipe + re-ingest. **2,108 → 2,418 chunks**, of which **310 are
  `njac_history`**. Fresh index, so still 0 orphaned vectors (matches chunk count exactly).
- **Verified against the eval set's own question and the live corpus**: in the isolated
  single-document eval corpus, `N.J.A.C. 5:23-12.5`'s new history chunk ranked #2 (score 0.501,
  contains both "2014" and "2009") for q15's exact question. Against the live re-ingested
  production corpus, it ranked **#1** (score 0.740), and `/query` returned: *"...the elevator
  registration fee section (5:23-12.5) was last amended by R.2014 d.149, effective October 6,
  2014."* — a correct, cited answer where there was previously no indexed answer at all.
- **Found, but explicitly not fixed here**: `N.J.A.C. 5:23-4.20(c).2` is a single 2,038-word
  chunk — `_chunk_lettered_piece` groups/splits *between* numbered items but has no level-4 split
  for one numbered item that's already oversized on its own.
  `NJ/eval/chunking_strategy.md`'s original design sketched a "sentence-level fallback" for
  exactly this case; it was never actually implemented. Pre-existing (not introduced or worsened
  by this session's changes), and plausibly hurts retrieval the same way the fence-question
  dilution bug did — just from an unfocused *oversized* chunk rather than a diluted merged one.
  Tracked in `PLAN.md`'s backlog rather than fixed here, to keep this session's change scoped to
  amendment-history indexing.
  **Resolved 2026-09-04** — see "Oversized single-item chunk splitting" below.
- Backend tests: 85 passed + 1 xfailed → **89 passed + 0 xfailed**.

### Oversized single-item chunk splitting

Picked up as its own fix right after the amendment-history work, following the same pattern: a
real gap found while fixing something else, worth chasing down rather than just noting. A quick
corpus-wide scan for oversized `njac_section` chunks (the same kind of check that surfaced the
fence-question dilution bug) found **36 chunks up to 2,803 words** — `5:23-4.20(c).2` (found
above) wasn't an isolated case.

- **Root cause, more precisely than originally described**: two distinct dead-ends in
  `_chunk_lettered_piece`, not one. (1) The early return when `_split_on(NUMBERED_SUB_RE, piece)`
  finds no numbered items at all — a whole lettered piece (or whole section, if it has no lettered
  subsections either) with no further structure, e.g. `N.J.A.C. 5:23-8.2` (1,638 words, no
  `(a)(b)(c)` and no `1. 2. 3.`). (2) `flush()`'s single-item case — either one genuinely oversized
  numbered item (`5:23-4.20(c).2`), or an oversized *intro* block with no numbered item of its own
  (the `"?"`-citation case from the fence-question fix, e.g. `N.J.A.C. 5:23-1.4.?`, 1,186 words).
  All three variants funnel through code that had no size check at all once structural splitting
  was exhausted.
- **Fix**: `_split_oversized_text(doc_id, title, header, citation, text)` — sentence-level
  grouping via `split_sentences()` (the same function `_chunk_history_text()` already uses for
  oversized History blocks, not duplicated), producing `citation (1)`, `citation (2)`, ... parts
  each within `MAX_CHUNK_WORDS`. Wired into both dead-ends above. This is the level-4
  "sentence-level fallback" `NJ/eval/chunking_strategy.md` sketched at design time ("Only fall
  back to sentence-level splitting inside a single numbered item if that item alone exceeds
  ~400 words (rare in this sample, but possible in denser subchapters like the building
  subcode)") — correctly anticipated, just never actually built until now.
- **Verified against all 36 originally-oversized chunks** (a standalone corpus-wide scan, not
  just the one example found earlier): **35 of 36 fixed**. The one still over cap —
  `N.J.A.C. 5:23-3.4(a).1 (2)`, 560 words (was 2,068) — is a PDF-extracted plan-review
  responsibility **table** (rows of code-section/discipline/responsibility triples run together
  with no sentence-ending punctuation for `split_sentences()` to find a boundary on). Same
  category of difficulty Phase 0 already flagged ("§12.6 has real fee tables that a naive
  sentence-chunker would flatten into unreadable text") — a real fix means table-aware
  extraction, a materially different and larger problem than chunking logic. Accepted as a
  residual limitation rather than chased further here; tracked in `PLAN.md`'s backlog. (At the
  time this was written, a second, unrelated 511-word chunk over cap belonged to `52_27D_119.pdf`'s
  generic chunker -- moot now, see "Structure-aware chunker for statute PDFs" below: that document
  isn't generic-chunked anymore.)
- **Tests**: two new `test_chunkers.py` cases — a single oversized numbered item splits into
  multiple word-capped, correctly-suffixed chunks (with neighboring items left untouched), and an
  oversized lettered piece with no numbered structure at all splits the same way.
- **Re-ingested the full 19-document corpus**: 2,418 → 2,482 chunks. Backend tests:
  89 passed + 0 xfailed → **91 passed + 0 xfailed**.

### Structure-aware chunker for statute PDFs

Continuing "chunking/retrieval quality" work (user's framing) after the oversized-chunk fix,
without a specific bug already in hand to chase this time -- so the investigation started from the
data itself, the same way the fence-question dilution bug was originally found: look at what's
actually indexed, not just what the code is supposed to do.

**Investigation.** `52_27D_119.pdf` (the UCC Act, 2nd-largest single document in the corpus by
chunk count) is a LexisNexis-exported "New Jersey Annotated Statutes" PDF, not plain statute
text. Checked its structure directly (page dumps, marker counts) and found it has the *exact* same
per-section pattern as the NJAC exports -- repeated page boilerplate, `History`, `Annotations`,
`End of Document` (134 sections, 100% with `History`, 76 with `Annotations`) -- but it was being
routed through the **generic** (word-count) chunker, which has zero structural awareness. Each
statute section is really: `[short operative text]` + `[case-law summaries under LexisNexis
headnote topic tags]` + `[Cross References / Research References]`, all chunked as undifferentiated
prose. Concrete example: `§ 52:27D-131` ("Construction permits...") is a 4-page section; pages 1-2
are ~2 paragraphs of actual statute text, pages 3-4 are **entirely** case-law summaries and
cross-reference lists with zero operative content. And this wasn't hypothetical: **that exact page
was one of the top-3 retrieved chunks for the original fence-permit question**, before this
session's njac.py fixes -- pure annotation noise competing for a retrieval slot against real
regulatory content.

This is a materially different kind of finding than the three chunking bugs above: those were
unambiguous engineering defects; this was a scope/design question (is case-law commentary useful
content here, or noise to strip?) plus a build of comparable size to `njac.py` itself. Presented
the finding and three options (build a real structure-aware chunker, a cheaper regex-only
mitigation, or just document and move on) rather than unilaterally committing to the larger build.
User picked the structure-aware chunker.

**Design.** Rather than duplicate `njac.py`'s ~250 lines of recursive lettered/numbered splitting,
oversized-chunk fallback, and History handling for a second, structurally-identical format,
extracted the shared engine into `app/chunkers/_legal_doc.py`, config-driven via a
`LegalDocConfig` dataclass (citation prefix, chunk-type names, section/lettered/numbered regexes,
page-boilerplate patterns, cross-reference patterns). `njac.py` is now a thin
NJAC-specific config wrapper around it; `app/chunkers/statute.py` is a second, equally thin
wrapper for the Lexis-statute format. This is the "Rule of Three" case for abstraction done right:
not extracted speculatively ahead of a proven second use case, but the moment one genuinely
appeared -- verified the refactor didn't change njac.py's behavior at all (every pre-existing
njac.py test passes unmodified against the refactored engine).

Format differences configured, not hard-coded:
- **Citation pattern**: `§ 52:27D-XXX[.X][letter].` (note the period after the citation number --
  NJAC's format has none, e.g. `"§ 5:23-12.5 Registration fee"` vs. `"§ 52:27D-121. Definitions"`).
- **Lettered/numbered delimiters are the mirror image of NJAC's**: statutes use `a.`/`(1)`
  (letter+period, then parenthesized number) where NJAC uses `(a)`/`1.` (parenthesized letter,
  then number+period) -- confirmed via corpus-wide scan (64/134 sections have lettered
  subsections, 27/134 have numbered sub-items, so this is real structure worth splitting on
  properly, not a rare edge case worth punting to sentence-level fallback).
- **Page boilerplate**: a per-section LexisNexis breadcrumb (`Title > Subtitle > Chapter >
  Article`, different text per section since it names that section's own chapter/article -- matched
  structurally, from "LexisNexis...Annotated Statutes" up to the next true line-start heading,
  rather than as fixed text) and a "Current through New Jersey ... Session" register-currency line
  that changes with every legislative session (matched by line prefix, not the specific date).

**Annotations dropped, not indexed separately.** Unlike History (kept, same treatment as
`njac_history`), `Annotations` content here is dropped entirely rather than turned into its own
chunk type -- a deliberate decision, not an oversight. Case-law commentary about a statute is a
different kind of content from the statute's own text or its enactment history, and was the
concrete, measured source of the retrieval pollution that motivated this whole investigation.

**Two real bugs found and fixed while building this** (both in the shared engine, both benefiting
njac.py too even though njac.py's own tests never happened to exercise them):
1. The heading-strip/repeated-heading-dedupe logic (`_dedupe_repeated_heading`, and the
   heading-strip line in `chunk_legal_document`) constructed its match string as
   `f"§ {citation_num} {title}"` -- correct for NJAC's no-period format, but a **silent no-op**
   for every statute section (period present, so the constructed string never matched the real
   text). Found via a real output bug: a section's top-level chunk showed only its own heading
   text with no body, because the "intro" piece ahead of the first lettered subsection (which
   should have been just the heading) wasn't being stripped from *later* pieces correctly and the
   whole thing looked truncated at first glance -- turned out to be expected intro-chunk behavior
   once traced through properly, but tracing it surfaced this real, separate bug: repeated
   mid-section heading duplicates were never being deduped for statute text at all. Fixed with a
   single shared, period-tolerant heading regex (`_heading_pattern`) used by both call sites.
2. 58 of 134 statute sections have **no** `Annotations` block at all -- for those, the trailing
   `LexisNexis(R) New Jersey Annotated Statutes / Copyright ...` footer (present in literally every
   section) has no `Annotations` label ahead of it to trigger the usual stripping, and was leaking
   straight into the **History** chunk for those sections (found live, e.g. `52:27D-122.1`). Fixed
   with a dedicated boilerplate pattern stripped unconditionally, before the History/Annotations
   split ever happens.

**Verified against the real corpus.** Re-ingested all 19 documents: `52_27D_119.pdf` went from
318 generic chunks to **437 structured ones** (303 `statute_section` + 134 `statute_history`).
Corpus total: 2,482 → **2,601 chunks**. Confirmed zero chunks in the whole corpus contain any
case-law content (`SELECT ... WHERE text LIKE '%Cherry Hill Towers%'` -> 0 rows, down from the
chunk that previously ranked in real query results for the fence question). Re-ran the exact
fence-permit question: the fence-provision chunk is still the top result (score 0.567, unchanged
from the njac.py fix), and the annotation-noise chunk that used to occupy the #5 slot is now a
real operative provision (`N.J. Stat. § 52:27D-123.17`, score 0.452) instead.

**New residual limitation found**: one statute chunk (`§ 52:27D-141.19.? (1)`, 628 words) is still
over the word cap -- a dense run of short quoted definitions ("`Air purifier` means...") that
`split_sentences()`'s grouping didn't cap correctly; not yet root-caused (possibly quote-mark or
abbreviation punctuation confusing sentence-boundary detection). Tracked in `PLAN.md` alongside the
pre-existing table-chunk limitation rather than chased further here -- 2 chunks out of 2,601.

**Tests**: 8 new `test_statute_chunker.py` cases -- detection, basic chunking, boilerplate/
breadcrumb stripping, lettered subsection splitting, numbered sub-item splitting, History
separated from dropped Annotations, and the no-Annotations copyright-footer regression. Backend
tests: 91 passed + 0 xfailed → **99 passed + 0 xfailed**.

### Visual/design QA pass

Phase 4's last open item -- functionality had been verified throughout, but nobody had reviewed
layout, responsiveness, or dark mode in a real browser session. Also folded in a decision from
earlier the same day: replacing `DocumentList`'s native `window.confirm()` delete confirmation
with an in-app modal (see the dedicated note further up this file for that discussion -- not a
correctness bug, just a visual-consistency gap, deliberately deferred here rather than fixed
standalone).

**Tooling limitation hit immediately**: neither `resize_window` nor real OS-level dark mode could
be reliably driven in the automation environment used for this session -- `resize_window` reported
success but `window.innerWidth` never actually changed (confirmed via direct JS inspection), and
there's no dedicated dark-mode-emulation tool available. Worked around both: dark mode was
verified by injecting a `<style>` block setting the exact CSS custom property values the real
`@media (prefers-color-scheme: dark)` block sets (copied directly from `index.css`, kept in sync
with it -- not a separate simulated palette); narrow viewports were verified by constraining
`#root`'s width via injected CSS and checking `scrollWidth` vs `clientWidth` directly rather than
trusting the screenshot alone.

**Found and fixed 3 real issues:**

1. **Dark mode: hardcoded confidence badge colors.** A scan for hex colors not routed through a
   CSS variable turned up exactly three lines -- `.confidence-high/medium/low` in `App.css` -- the
   *only* hardcoded colors in the entire stylesheet; everything else already properly used the
   `--text`/`--bg`/`--accent`/etc. variable system. Visually confirmed via the dark-mode injection
   technique above: these badges rendered as bright pastel light-mode chips (`#dcfce7`, `#fef3c7`,
   `#fee2e2` backgrounds) floating on the near-black dark background, jarringly inconsistent with
   every other badge in the app (the `njac`/`generic` chunker badges, the `superseded` badge, and
   the `llm-badge` all correctly used theme variables already and adapted fine). Fixed by adding
   `--confidence-high-bg`/`-fg`, `--confidence-medium-bg`/`-fg`, `--confidence-low-bg`/`-fg`
   variables to `index.css` (light defaults matching the original hardcoded values exactly, dark
   overrides using deep desaturated backgrounds with bright foreground text -- the same treatment
   `--warn-bg` already used for the low-confidence warning box, which is why that box already
   looked correct in dark mode without needing any fix). While auditing this, also noticed
   `--danger` and `--success` (used as plain text color in several places -- error messages, the
   Delete link, "Done"/"Error" upload-item status text) had no dark-mode override either; they were
   technically legible against the dark background but visibly muted. Brightened both for dark mode
   (`#b91c1c` → `#f87171`, `#15803d` → `#4ade80`) for consistency, verified by zooming into the
   real "Delete" link before and after -- clearly more legible after.
2. **Responsive: `DocumentList`'s document table had no scroll container.** Confirmed via direct
   `scrollWidth`/`clientWidth` inspection (not just a visual guess) that at a simulated 390px
   width, `#root`'s `scrollWidth` (517px) exceeded its `clientWidth` (386px) -- the table (a plain
   HTML `<table>` with five columns: Title, Chunker, Chunks, Ingested, actions) had nowhere to go
   but overflow, with no way for a user to reach the cut-off Replace/Delete actions. Fixed by
   wrapping the table in a new `.table-scroll { overflow-x: auto }` div with `min-width: 600px` on
   the table itself, so it becomes independently horizontally scrollable within its own area
   instead of breaking the page's layout containment -- the same "wide content scrolls in its own
   container, the page body never does" principle used elsewhere for exactly this class of problem.
   Verified the fix numerically too: `#root`'s `scrollWidth` and `clientWidth` became exactly
   equal (386 == 386) after the fix, with the `.table-scroll` div itself correctly showing the
   overflow (`scrollWidth: 600` vs `clientWidth: 338`, `overflow-x: auto`). Also added
   `flex-wrap: wrap` to `.app-header`, since the title and tab nav crowded/overlapped at the same
   narrow width without it.
3. **Delete confirmation modal.** New `ConfirmDialog.tsx` component, reusing the existing
   `.modal`/`.modal-overlay` pattern already established by `ChunkPreviewModal` for visual
   consistency (same rounded card, same overlay treatment) rather than inventing a new modal
   style. Adds `role="dialog"`, `aria-modal`, and `aria-labelledby` (accessibility niceties
   `ChunkPreviewModal` doesn't have either -- deliberately not retrofitted there, to keep this
   change scoped to the one component actually being touched) and closes on Escape or an overlay
   click, in addition to explicit Cancel/Confirm buttons. `DocumentList.handleDelete` was split
   into `setPendingDelete(doc)` (opens the dialog) and `confirmDelete()` (does the actual delete,
   called from the dialog's `onConfirm`).

**A mistake made and corrected earlier the same session, surfaced again here for context**: this
pass is when the "browser automation can't observe native dialogs" limitation (documented in the
click-to-browse section above) was first discovered -- an accidental real click on a live file
input during that unrelated investigation is what led to figuring out `resize_window` and
dark-mode emulation would need workarounds here too, before this pass properly began.

**Verified live against the running app** (real dev corpus, non-destructively): opened the delete
dialog on a real document and confirmed it renders as a themed in-app modal, not a native browser
`confirm()` popup -- title "Delete document", the exact same message text the old `window.confirm`
used, a "Cancel" button and a red "Delete" button; clicked Cancel and confirmed the document list
was unchanged (no delete occurred). Confirmed the wide desktop layout is pixel-identical to before
the `flex-wrap` header change (only affects narrow widths, as intended).

**Tests**: 7 new `ConfirmDialog.test.tsx` cases (renders title/message/confirm label, calls
`onConfirm`, calls `onCancel` on the Cancel button/overlay click/Escape, does *not* call `onCancel`
on an inside click, applies the danger class). `DocumentList.test.tsx`'s three `window.confirm`-
mocked delete tests rewritten to exercise the real dialog via `role="dialog"` + `within()` queries
instead (one of them now also asserts `window.confirm` was never called), plus one new test for
the Escape-to-cancel path. Frontend tests: 43 passed → **51 passed**.

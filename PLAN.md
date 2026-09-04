# PLAN.md

Progress checklist against `dream.md`'s original build plan, plus everything built beyond it.
For the full narrative/rationale behind each decision, see `docs/AllDevFlow.md`.

## Phase 1 — Core Backend

- [x] FastAPI setup
- [x] PDF parsing (pdfplumber)
- [x] Chunking (structure-aware NJAC chunker + generic sentence chunker, pluggable registry)
- [x] Embeddings (local sentence-transformers, `all-MiniLM-L6-v2`)
- [x] FAISS index (`IndexFlatIP`, cosine similarity) + SQLite metadata store
- [x] `/query` endpoint (retrieval + programmatic citations + similarity-based confidence)

## Phase 2 — OCR + DOCX/TXT Support

- [x] DOCX ingestion (python-docx)
- [x] TXT ingestion
- [x] OCR fallback for scanned PDF pages (Tesseract + PyMuPDF rasterization) — verified against
      both a real generated scanned PDF and via `/upload`
- [x] Frontend upload restrictions match backend capability (`.pdf`/`.docx`/`.txt` accepted;
      outdated "PDF only, Phase 2 not started" messaging removed)

## Phase 3 — Citations + Confidence

- [x] Citations derived programmatically from retrieved chunks (never trusted from LLM output)
- [x] Similarity-based confidence score (FAISS cosine top-1)
- [x] Confidence tiers surfaced in the UI (high/medium/low badges, low-confidence warning)

## Phase 4 — React UI

- [x] Upload page (drag-and-drop + click-to-browse, per-file status, processed-document list)
- [x] Q&A page (question box, answer card, citations, chunk previews + modal)
- [x] Summary page (document picker, generate summary, truncation notice, download `.txt`)
- [x] Document versioning UI (Replace action, superseded badge, show-all-versions toggle)
- [ ] Visual/design QA pass (layout, responsiveness, dark mode) — functionality is verified,
      appearance has not been formally reviewed

## Phase 5 — Scaling + Optional Cloud

- [ ] Pinecone/Weaviate adapter
- [ ] Authentication
- [ ] Multi-user support
- [ ] Rate limiting

## Beyond the original dream.md scope

- [x] Duplicate-upload detection (content-hash based, 409 Conflict)
- [x] Document deletion (`DELETE /documents/{doc_id}`)
- [x] Document versioning / supersede-and-keep-history (`supersedes_doc_id`, `is_latest`,
      `/documents/{doc_id}/versions`)
- [x] Pluggable LLM provider switch (Anthropic ↔ Ollama via `RAG_LLM_PROVIDER`), including
      `RAG_OLLAMA_NUM_GPU` for CPU/GPU offload tuning
- [x] Summary generation validated end-to-end against a real local LLM (Ollama), not just the
      unconfigured-503 path
- [x] Backend test suite — 82 pytest tests (81 passing + 1 documented xfail): chunkers, extractors
      (including real Tesseract OCR), LLM provider switching (mocked), vector_store internals, all
      4 routers, full upload→query→summary→delete integration lifecycles, and the eval-set runner
      below
- [x] Frontend test suite — 43 Vitest + React Testing Library tests, including regression tests
      for stale-state UI bugs found and fixed along the way (3 originally, plus the async-upload
      Replace-flow bug below)
- [x] Git repository initialized and pushed to GitHub (`shalisarakkal/construction`)
- [x] CI pipeline (`.github/workflows/ci.yml`) — runs backend pytest (incl. installing Tesseract
      for the real-OCR test) and frontend vitest + build on every push/PR to `master`
- [x] Fixed corpus drift — deleted the duplicate `njac_5_23.pdf` (combined UCC doc, 1141 chunks)
      from the live dev corpus, restoring it to the documented 17-document/1463-chunk baseline
      (see `docs/AllDevFlow.md` Phase 2 close-out)
- [x] Configurable default Top-K (`frontend/.env`, `VITE_DEFAULT_TOP_K`) — was hardcoded to 5 in
      `QuestionBox.tsx`; now 3 by default, since a higher top-k means a longer prompt and CPU-backed
      Ollama queries could take several minutes
- [x] Eval-set runner (`backend/tests/test_eval_set.py`) — wires up the previously-unused
      `NJ/eval/eval_set.json` (15 hand-verified Q&A cases against `njac_5_23_12.pdf`) as a real,
      CI-running retrieval-quality regression check. Ingests just that one document into an
      isolated corpus, matching the eval set's original single-document design (running it
      against the full multi-document production corpus gives noisier, less meaningful results,
      and originally also surfaced a corpus-drift bug — a duplicate `njac_5_23.pdf` sitting in the
      live corpus, since fixed, see below). Surfaced two genuine findings in the process:
      - The amendment-history case (q15) is a documented `xfail`, not a pass/fail toggle: section
        retrieval finds the right section (5:23-12.5) but the actual answer (the 2014 amendment
        date/fee change) isn't retrievable, because `njac.py`'s `HISTORY_SPLIT_RE` deliberately
        strips each section's History block before indexing. This was always true; the eval set
        just never ran before to reveal it.
      - The negative-control confidence threshold from `docs/AllDevFlow.md`'s original Phase 1
        note (~0.34, "don't answer below ~0.4-0.5") doesn't hold as tightly under re-measurement —
        one of the two negative controls now scores 0.58, still well below genuine matches
        (0.62-0.84) but above the originally suggested cutoff. Test uses a looser 0.65 bound.
- [x] `/upload` moved to a background job — the router now does only the cheap synchronous checks
      (duplicate-hash, supersedes-target validity) before returning `202 {job_id, status: "queued"}`;
      the slow extract/chunk/embed/store pipeline runs in a FastAPI `BackgroundTasks` call (off the
      event loop, via its threadpool) tracked in a new `jobs` SQLite table, polled via
      `GET /upload/jobs/{job_id}`. Frontend's `UploadComponent` polls that endpoint (800ms interval)
      and shows a `Processing…` state. Verified against a real running server (isolated storage
      dir, not the dev corpus): POST returned instantly with `status: "queued"`, transitioned to
      `processing`, then `done` with the full result once ingestion finished.
- [x] Fixed `DocumentList`'s "Replace" action for the now-async `/upload` — it was still awaiting
      `uploadDocument()` as if it resolved with the finished result, refreshing the document list
      right after the job was enqueued rather than after it actually finished superseding the old
      document. Now polls the job (shared `pollJobUntilDone()`, factored out into
      `frontend/src/uploadJob.ts`) and only refreshes once it completes; verified manually in a
      real browser against isolated storage (success path, and the 409-duplicate error path
      leaving the table unchanged).
- [x] Fixed a real retrieval miss found via manual Q&A testing ("Any special requirement to build
      a fence around the property?" wrongly answered "Not enough information" even though the
      corpus has a directly relevant provision). Root-caused to two bugs in `app/chunkers/njac.py`:
      1. Numbered-item grouping bundled topically-unrelated permit exemptions into one chunk up to
         the 500-word cap, diluting a short but substantive item's embedding with 4 unrelated
         neighbors. Fixed with `MIN_GROUP_WORDS = 20`: an item that size or larger closes its own
         chunk instead of continuing to absorb subsequent unrelated items; genuinely tiny
         (context-free) items still group together as before.
      2. `_split_on()` silently dropped any text before the first regex match — confirmed as real
         content loss on the live corpus (`njac_5_23_2.pdf`'s actual "(b) The following are
         exceptions from (a) above:" intro sentence was missing from the ingested chunk). Fixed to
         keep that text as a leading piece, merged into the first real item's group instead of
         lost.
      Re-ingested the full 17-document corpus with the fix: 1,463 → 2,055 chunks (finer-grained,
      as expected). Verified the original failing question now retrieves the correct chunk
      (`N.J.A.C. 5:23-2.14(b).9`, score 0.567, previously outside the top 9 of a top-20 request)
      and the LLM's answer now correctly cites the real fence-permit-exemption provision.
- [x] Added `vector_store.compact_index()` + `backend/scripts/compact_faiss_index.py` — rebuilds
      the FAISS index from only live chunks' vectors (reconstructed from the existing flat index,
      no re-embedding needed), dropping orphaned vectors from past deletes/supersedes/schema-reset
      re-ingests. Found via the fence-question investigation: the dev corpus's FAISS index held
      3,035 vectors for only 1,463 live chunks (52% dead weight), silently shrinking every query's
      effective top_k. The corpus reingest above already produced a fresh, orphan-free index
      (2,055 vectors == 2,055 live chunks), so `compact_index()` wasn't needed this time, but is
      now available as reusable maintenance tooling for future deletes/supersedes without a full
      re-ingest.
- [x] Source corpus completed against the authoritative N.J.A.C. 5:23 table of contents
      (`https://www.nj.gov/dca/codes/codreg/ucc.shtml`, linked from `NJ/links.md` but not itself
      previously checked — `NJ/links.md`/`current.shtml` turned out to be a narrower "external
      code cross-reference" page, not a full index, which is why several subchapters were never in
      it despite existing). All 17 listed subchapters are now present in `NJ/pdfs/`: the user
      manually downloaded the two that were missing, `njac_5_23_10.pdf` (Radon Hazard Subcode) and
      `njac_5_23_12A.pdf` (Optional Elevator Inspection Program), and both were ingested into the
      live corpus via the real `/upload` API (35 and 18 chunks). Corpus is now 19 documents, 2,108
      chunks.
- [x] Confirmed N.J.A.C. 5:23-3.14/3.15/3.16/3.18/3.20/3.21/3.22 (Building/Plumbing/Electrical/
      Energy/Mechanical/1&2-Family/Fuel Gas subcodes) are indexed — they're sections within
      `njac_5_23_3.pdf` (already in the corpus since Phase 1), not separate files. Each mostly just
      adopts an external model code (IBC/NEC/IECC/etc.) by reference, so what's indexed is NJ's
      amendments to those codes, not the base code text — consistent with Phase 0's decision not to
      download the copyrighted base codes themselves.

## Out of scope (explicit decisions, not oversights)

- N.J.A.C. 5:21 (Residential Site Improvement Standards / RSIS) — a different NJAC chapter
      covering subdivision/site design standards (streets, parking, stormwater, utilities) for
      residential development, not building construction. User decision 2026-09-04: skip unless
      requested later. See `docs/AllDevFlow.md`'s Phase 1 "Scope check" note for the reasoning.

## Known issues / backlog

- [ ] No schema migration tooling — every schema change so far has required a full storage wipe +
      re-ingest
- [ ] Amendment-history text isn't indexed (see eval-set finding above) — would need `njac.py` to
      stop discarding the `History:` block, store it as separate low-priority chunks or metadata
      instead of dropping it entirely
- [ ] This dev machine's GPU (GTX 1060 3GB) can't meaningfully accelerate the 8B Ollama model —
      CPU-only (`RAG_OLLAMA_NUM_GPU=0`) is currently faster than automatic partial GPU offload
- [ ] The `(a)`/`(b)`-only "intro" chunk citation falls back to a cosmetic `"?"` placeholder (e.g.
      `N.J.A.C. 5:23-2.3(a).?`) when a lettered piece's oversized intro text has no numbered item
      of its own — harmless (chunk is still fully indexed and searchable) but not a clean citation
      for a user-facing answer; a real fix would derive a better label than `"?"` for that case

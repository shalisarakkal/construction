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
- [x] Visual/design QA pass (layout, responsiveness, dark mode) — see "Beyond dream.md scope"
      below for what was found and fixed (dark-mode confidence badges, a responsive table
      overflow, and the delete-confirmation modal).

## Phase 5 — Scaling + Optional Cloud

- [x] Pinecone/Weaviate adapter — three-way switch built 2026-09-04
      (`RAG_VECTOR_STORE_PROVIDER=faiss|pinecone|weaviate`, Weaviate targeting Weaviate Cloud, not
      self-hosted), same provider-switch pattern as the LLM adapter. Unit-tested against fake
      Pinecone/Weaviate doubles (23 vector_store tests, backend total 99 → 107). **Pinecone verified
      live end-to-end against the user's real account** (isolated throwaway index, not the real
      corpus): add, search (real ~1.0 cosine score on an exact match), delete, and index cleanup all
      confirmed working over the real network. FAISS's default path also re-verified live against
      the real 19-document/2,601-chunk dev corpus (server started, `/documents`, `/query` incl. the
      fence-question regression check, `/documents/{id}/chunks`, `/documents/{id}/versions` all
      correct) after the 3-way refactor. **Weaviate verified live end-to-end** too, against the user's
      real Weaviate Cloud cluster (throwaway collection, deleted after) -- add/search/delete all
      confirmed over the real network, same as Pinecone. Live verification caught a real bug on the
      way: the collection's vector index was hardcoded to `hnsw`, but this cluster's serverless tier
      only allows `hfresh` (rejected with a 422 on first attempt) -- fixed by switching to the
      non-deprecated `vector_config=Configure.Vectors.self_provided(vector_index_config=Configure.
      VectorIndex.hfresh(...))` API. All three backends (FAISS, Pinecone, Weaviate) are now verified
      live. Switching the env var does **not**
      migrate existing vectors between backends -- deferred as **Phase 5a** (a separate
      re-embed-from-SQLite-and-re-upsert migration script; see docs/AllDevFlow.md's "Phase 5"
      section for the full reasoning).
- [ ] Phase 5a — vector-store migration script (re-embeds stored chunk text and re-upserts into
      whichever backend is newly active, so switching `RAG_VECTOR_STORE_PROVIDER` doesn't strand
      already-ingested documents). Not started.
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
- [x] Backend test suite — 99 pytest tests, all passing (grew from an initial 82 as chunking bugs
      were found and fixed — see below): chunkers (njac.py and statute.py), extractors (including
      real Tesseract OCR), LLM provider switching (mocked), vector_store internals, all 4 routers,
      full upload→query→summary→delete integration lifecycles, and the eval-set runner below
- [x] Frontend test suite — 51 Vitest + React Testing Library tests, including regression tests
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

- [x] **Amendment-history text is now indexed.** `njac.py`'s `HISTORY_SPLIT_RE` used to discard
      every section's `History:` block entirely (amendment dates, N.J.R. citations, and
      plain-English change descriptions — e.g. "R.2014 d.149, effective October 6, 2014...Updated
      the fee amounts"). Added `_chunk_history_text()`: indexes each section's history as its own
      `chunk_type: "njac_history"` chunk (citation suffixed `... History`, or `... History (N)` for
      sections whose history is too long for one chunk — up to 1,901 words for the most-amended
      section found, `5:23-4.20`). Kept separate from operative-text chunks rather than merged in,
      so a regulatory-text query's embedding isn't diluted by decades of unrelated amendment dates,
      and a "when was this amended" query gets a chunk that's *entirely* history, not diluted by
      substantive rule text either.
      - **Found and fixed a second bug in the process**: the trailing "Annotations / Notes /
        Chapter Notes / NEW JERSEY ADMINISTRATIVE CODE / Copyright..." footer (present at the end
        of literally every section in the corpus — verified 291/291) was leaking straight into
        operative_text's indexed, retrievable content whenever a section had *no* History block to
        split it off first. Found live in 22 already-ingested chunks (e.g. `N.J.A.C. 5:23-1.2`).
        Now stripped from both operative_text and the new history chunks.
      - `backend/tests/test_eval_set.py`'s q15 ("When was the registration fee section last
        amended...") was a documented `xfail` for exactly this gap — now passes for real; the
        `xfail` marking was removed rather than kept as a stale pass/fail toggle.
      - Re-ingested the full 19-document corpus: 2,108 → 2,418 chunks (310 of them `njac_history`).
        Verified live against the real corpus: `N.J.A.C. 5:23-12.5`'s history chunk is now the
        **top** retrieved result (score 0.740) for the eval set's amendment-history question, and
        `/query` returns a correct, cited answer ("...amended by R.2014 d.149, effective October 6,
        2014") instead of the old "not indexed" gap.
      - Backend tests: 85 → 89 passed (+3 new chunker tests, q15's `xfail` → real pass).
- [x] **Oversized single-item chunks now split further.** `_chunk_lettered_piece` only ever
      grouped/split *between* numbered items — a single item (or an oversized intro block with no
      numbered item of its own) that was already too big on its own became one oversized chunk
      regardless of size. Found live: 36 chunks up to 2,803 words (`N.J.A.C. 5:23-3.14(b).31`).
      Added `_split_oversized_text()` — the level-4 "sentence-level fallback"
      `NJ/eval/chunking_strategy.md` originally sketched for this case but never implemented —
      reused at both dead-ends (`_chunk_lettered_piece`'s no-numbered-items early return, and
      `flush()`'s single-oversized-item case), the same sentence-grouping approach as the
      amendment-history fix's `_chunk_history_text()`. Re-ingested the full 19-document corpus:
      2,418 → 2,482 chunks. **35 of 36 oversized chunks fixed** — the one remaining
      (`N.J.A.C. 5:23-3.4(a).1 (2)`, 560 words) is a PDF-extracted table with no sentence
      punctuation to split on, tracked separately in the backlog below (a different, harder
      problem — table-aware extraction, not chunking logic). Backend tests: 89 → 91 passed.

- [x] **Structure-aware chunker for LexisNexis-exported NJ statute PDFs** (`app/chunkers/statute.py`),
      replacing the generic (word-count) chunker for `52_27D_119.pdf` (the UCC Act — 2nd-largest
      document in the corpus). Found while continuing chunking/retrieval-quality work: this document
      has the *exact* same per-section structure as the NJAC exports (repeated page boilerplate,
      `History`, `Annotations`, `End of Document` — 134 sections) but was going through the generic
      chunker, which has zero structural awareness — case-law annotations (the bulk of the
      document's page count) were being chunked as undifferentiated prose right alongside the
      actual short operative statute text. Confirmed this was actively hurting retrieval: a
      pure-annotation chunk (a case citation + cross-reference list, zero operative content) was
      one of the top-3 results for the original fence-permit question, before any of this
      session's fixes.
      - Extracted the shared chunking engine from `njac.py` into `app/chunkers/_legal_doc.py`
        (config-driven: citation prefix, chunk-type names, section/lettered/numbered regexes,
        page-boilerplate patterns) once a genuine second consumer appeared, rather than duplicate
        ~250 lines of recursive lettered/numbered splitting, oversized-chunk fallback, and History
        handling. `njac.py` is now a thin NJAC-specific config wrapper; behavior is unchanged
        (verified: all pre-existing njac.py tests pass unmodified against the refactor).
      - `statute.py` configures the same engine for `§ 52:27D-XXX[.X][letter].` citations,
        `a.`/`(1)` lettered/numbered delimiters (statutes use the mirror-image convention from
        NJAC's `(a)`/`1.`), and statute-specific page boilerplate (a per-section LexisNexis
        breadcrumb, a "Current through ..." register-currency line that changes every session).
      - **Annotations (case-law digest) is dropped entirely**, not indexed as a separate chunk
        type like History — a deliberate design decision, not an oversight: case-law commentary
        about a statute is fundamentally different content from the statute's own text or its
        enactment history, and was the concrete source of the retrieval pollution found. History
        (enactment/amendment log) is indexed separately, same treatment as `njac_history`.
      - Found and fixed a real bug while building this: the heading-strip/dedupe logic assumed no
        period after the citation number (true for NJAC: `"§ 5:23-12.5 Registration fee"`, false
        for statutes: `"§ 52:27D-121. Definitions"`) — silently no-opped both the repeated-heading
        dedupe and the operative-text heading strip for every statute section. Fixed with a shared,
        period-tolerant heading regex used by both.
      - Also found and fixed: 58 of 134 statute sections have no `Annotations` block at all, so the
        trailing LexisNexis/copyright footer (present in *every* section) wasn't being caught by
        the usual Annotations-triggered stripping — it was leaking straight into the History chunk
        for those sections. Stripped unconditionally via a dedicated boilerplate pattern instead.
      - Re-ingested the full 19-document corpus with the new chunker: `52_27D_119.pdf` went from
        318 generic chunks to 437 structured ones (303 `statute_section` + 134 `statute_history`).
        Corpus total: 2,482 → 2,601 chunks. Verified live: zero chunks in the whole corpus now
        contain any case-law content (`SELECT ... WHERE text LIKE '%Cherry Hill Towers%'` → 0, down
        from the chunk that previously ranked in real query results); re-ran the fence-permit
        question and confirmed the annotation-noise result was replaced by a real operative
        provision (`N.J. Stat. § 52:27D-123.17`).
      - Tests: 8 new `test_statute_chunker.py` cases (detection, basic chunking, boilerplate/
        breadcrumb stripping, lettered/numbered splitting, History-separated-from-dropped-
        Annotations, the no-Annotations copyright-footer regression). Backend tests: 91 → 99 passed.
- [x] **Visual/design QA pass** — verified in a real browser (dark mode simulated via CSS variable
      injection, since neither `resize_window` nor OS-level dark mode could be reliably driven in
      the automation environment used; narrow viewports simulated via a constrained container
      since window resize had no effect there either). Found and fixed 3 real issues:
      1. **Dark mode**: `.confidence-high/medium/low` badges (`AnswerCard`) were the only hardcoded
         colors in the whole stylesheet — no dark-mode override, so they rendered as bright
         light-mode chips floating on the dark background, inconsistent with every other themed
         badge. Fixed with new `--confidence-*-bg`/`--confidence-*-fg` CSS variables (light
         defaults + dark overrides, following the same pattern `--warn-bg` already used). Also
         brightened `--danger`/`--success` for dark mode (`#b91c1c`/`#15803d` were technically
         legible against the dark background but noticeably muted; now `#f87171`/`#4ade80`).
      2. **Responsive**: `DocumentList`'s document table had no scroll container — confirmed via
         `scrollWidth`/`clientWidth` inspection that it overflowed its parent at narrow widths with
         no way to see the cut-off columns. Wrapped in `.table-scroll { overflow-x: auto }` so the
         table scrolls within its own area instead of breaking the page layout. Also gave
         `.app-header` `flex-wrap` so the title and tab nav don't crowd each other at narrow widths.
      3. **Delete confirmation modal**: replaced `DocumentList`'s native `window.confirm()` with a
         new `ConfirmDialog` component (user decision 2026-09-04, folded into this pass) — reuses
         the existing `.modal`/`.modal-overlay` pattern from `ChunkPreviewModal` for visual
         consistency, adds `role="dialog"`/`aria-labelledby` and Escape-to-cancel (neither of which
         `ChunkPreviewModal` had either, not retrofitted there to keep this change scoped).
      - Verified live: dark-mode badge fix confirmed by injecting the exact dark CSS values and
        comparing before/after; table overflow fix confirmed by checking `#root`'s `scrollWidth`
        now equals its `clientWidth` at a simulated 390px width; delete dialog opened and cancelled
        against the real corpus (non-destructive) — themed correctly, no native browser dialog.
      - Tests: 8 new (`ConfirmDialog.test.tsx`) + `DocumentList.test.tsx`'s delete tests rewritten
        to exercise the in-app dialog instead of mocking `window.confirm`, plus a new Escape-key
        test. Frontend tests: 43 → 51 passed.
- [x] **Scope Q&A to selected document(s)** — user asked whether a question could be answered from
      just a chosen set of files rather than the whole corpus; agreed direction was a document
      multi-select in the existing UI (not folder-watching, which doesn't match how documents get
      ingested here). New optional `doc_ids` on `QueryRequest`, threaded through `vector_store.
      search()` into all three backends: FAISS filters in Python after a full `ntotal`-sized scan
      (free — `IndexFlatIP` computes a score against every vector regardless of requested `k`, so
      this costs nothing extra and is simpler than maintaining per-doc sub-indexes); Pinecone and
      Weaviate both gained real native filtered search (`filter={"doc_id": {"$in": ...}}` /
      `Filter.by_property("doc_id").contains_any(...)`), which required both to start storing
      `doc_id` as metadata/a property at upsert time (previously only `chunk_id` was stored). New
      `DocumentScopePicker` component (checkbox list + Select all/Clear, fetches `listDocuments()`
      same as `SummaryPage`) added as a sibling to `QuestionBox` rather than folded into it, to
      keep `QuestionBox`'s existing test suite untouched. Zero documents selected = search
      everything (unchanged default behavior). Verified live against the real corpus: a question
      scoped to one real document returned chunks from only that document; the same question
      unscoped still returned its usual multi-document spread. Backend tests: 107 → 113 passed.
      Frontend tests: 51 → 58 passed.

## Out of scope (explicit decisions, not oversights)

- N.J.A.C. 5:21 (Residential Site Improvement Standards / RSIS) — a different NJAC chapter
      covering subdivision/site design standards (streets, parking, stormwater, utilities) for
      residential development, not building construction. User decision 2026-09-04: skip unless
      requested later. See `docs/AllDevFlow.md`'s Phase 1 "Scope check" note for the reasoning.

## Known issues / backlog

- [x] ~~Click-to-browse doesn't open the file picker~~ — **closed, won't-fix, 2026-09-04.** User
      decision: ignore it. Two rounds of code-level inspection found no CSS/DOM bug; drag-and-drop
      remains a fully working alternative upload path. See `docs/AllDevFlow.md`'s dedicated
      section for full diagnostic history if this ever resurfaces.
- [ ] No schema migration tooling — every schema change so far has required a full storage wipe +
      re-ingest
- [ ] This dev machine's GPU (GTX 1060 3GB) can't meaningfully accelerate the 8B Ollama model —
      CPU-only (`RAG_OLLAMA_NUM_GPU=0`) is currently faster than automatic partial GPU offload
- [ ] The `(a)`/`(b)`-only "intro" chunk citation falls back to a cosmetic `"?"` placeholder (e.g.
      `N.J.A.C. 5:23-2.3(a).?`) when a lettered piece's oversized intro text has no numbered item
      of its own — harmless (chunk is still fully indexed and searchable) but not a clean citation
      for a user-facing answer; a real fix would derive a better label than `"?"` for that case
- [ ] Two chunks in the whole corpus are still over the 500-word cap: `N.J.A.C. 5:23-3.4(a).1 (2)`
      (560 words — a PDF-extracted plan-review responsibility **table**, row after row of
      code-section/discipline/responsibility triples with no sentence-ending punctuation for
      `split_sentences()` to find a boundary on) and `N.J. Stat. § 52:27D-141.19.? (1)` (628 words,
      found after adding `statute.py` — a dense run of short quoted definitions, e.g. `"Air
      purifier" means...`; not yet root-caused why `split_sentences()`'s grouping didn't cap it,
      possibly the quote-mark/abbreviation punctuation confusing sentence-boundary detection).
      Same category of difficulty as Phase 0's fee-table discovery ("a naive sentence-chunker
      would flatten tables into unreadable text") — accepted as a residual limitation given it's
      2 chunks out of 2,601, not chased further here.
- [ ] CAD/GIS file support -- user asked 2026-09-04 whether CAD/GIS files are supported; they
      aren't natively (`ingestion.py` rejects any extension besides `.pdf`/`.docx`/`.txt`
      outright). Splits into two very different-sized pieces of work:
      - **As `dream.md` actually scoped it** ("CAD/GIS notes → text: Treat exported PDF/TXT/DOCX
        as standard documents") -- this is largely already built: `generic_chunk()`'s own
        docstring already names "CAD/GIS export notes" as a target input, and any PDF/DOCX/TXT
        exported from a CAD/GIS tool ingests today with zero new code. The real gap is
        untested chunk quality, not missing support: `generic_chunk()` sentence-splits on
        `. ! ?` punctuation, an assumption that holds for regulatory prose but likely breaks on
        the sparse labels/notes-lists/title-block text typical of a CAD/GIS export (no real
        sentences to split on) -- and PDF text-extraction order for a drawing sheet often doesn't
        match visual reading order in the first place, before chunking even starts. Effort: small,
        roughly one focused session (comparable to this session's other chunking-quality fixes) --
        get 1-2 real sample exported files from the user, inspect actual extracted text shape, and
        likely add a line/label-based chunking path (mirroring the `looks_like_njac`/
        `looks_like_statute` sniff-and-branch pattern) if the sentence-based one produces
        garbage chunks on that shape of text. Blocked on the user supplying real sample files --
        can't responsibly estimate the fix without seeing what the actual extracted text looks
        like.
      - **Native CAD/GIS file parsing** (opening a raw `.dwg`/`.dxf`/`.shp`/`.geojson`/geodatabase
        directly, not an export) -- a genuinely different, much larger feature, not an extension
        of the above. Needs new per-format dependencies (`ezdxf` for DXF; DWG itself is a
        proprietary binary format needing a conversion step first; GDAL/Fiona/Shapely for GIS
        vector formats), a new definition of "extractable text" per format (DXF TEXT/MTEXT
        entities and block attributes; a shapefile's DBF attribute table; a GeoJSON `properties`
        object), a different chunking granularity (one chunk per entity/feature rather than per
        paragraph), schema additions (`chunks` has no field for a CAD layer name or geometry
        type), and arguably a different retrieval model altogether -- semantic similarity search
        over prose doesn't map cleanly onto spatial/geometric data. Effort: large, multi-session,
        closer to a new subsystem than a chunker addition -- would warrant its own phase-level
        plan rather than a single backlog line item if actually picked up.

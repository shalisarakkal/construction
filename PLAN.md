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
- [ ] Click-to-browse file picker bug — drag-and-drop works; clicking the dropzone to open the OS
      file dialog does not for at least one user/browser setup. Root cause not confirmed
      (suspected browser extension or dialog opening behind the window). Drag-and-drop is a fully
      working alternative in the meantime. See `docs/AllDevFlow.md`.
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
- [x] Backend test suite — 65 pytest tests: chunkers, extractors (including real Tesseract OCR),
      LLM provider switching (mocked), vector_store internals, all 4 routers, and full
      upload→query→summary→delete integration lifecycles
- [x] Frontend test suite — 38 Vitest + React Testing Library tests, including regression tests
      for 3 stale-state UI bugs found and fixed this session
- [x] Git repository initialized and pushed to GitHub (`shalisarakkal/construction`)
- [x] CI pipeline (`.github/workflows/ci.yml`) — runs backend pytest (incl. installing Tesseract
      for the real-OCR test) and frontend vitest + build on every push/PR to `master`

## Known issues / backlog

- [ ] `/upload` runs synchronously in the request handler — should move to a background job for
      large documents
- [ ] FAISS index only ever grows; delete/supersede leave orphaned vectors behind (acceptable at
      current corpus size, ~1,400 chunks)
- [ ] No schema migration tooling — every schema change so far has required a full storage wipe +
      re-ingest
- [ ] No automated eval-set runner — `NJ/eval/eval_set.json` exists but isn't wired into the test
      suite or CI
- [ ] Click-to-browse file picker bug (see Phase 4)
- [ ] Default Top-K=5 on the Q&A page makes CPU-backed Ollama queries slow (3-4 min at large
      top-k); consider lowering the default or showing an elapsed-time indicator
- [ ] This dev machine's GPU (GTX 1060 3GB) can't meaningfully accelerate the 8B Ollama model —
      CPU-only (`RAG_OLLAMA_NUM_GPU=0`) is currently faster than automatic partial GPU offload

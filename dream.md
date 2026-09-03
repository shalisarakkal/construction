RAG Application Build Plan

1. Document Ingestion Pipeline

Convert engineering PDFs, CAD/GIS notes, and images into clean text and embeddings.

1.1 File Upload Service (Backend)

Create /upload endpoint using FastAPI.

Accept file types: PDF, JPG/PNG, TXT, DOCX, CAD/GIS exported notes.

Store raw files under /storage/documents/{doc_id}/raw/.

1.2 Text Extraction

PDF → text: Use pdfplumber for page-by-page extraction.

CAD/GIS notes → text: Treat exported PDF/TXT/DOCX as standard documents.

Images → OCR: Use Tesseract or Azure Vision OCR.

1.3 Output Format

{
  "doc_id": "123",
  "title": "Bridge Design Notes",
  "pages": [
    { "page_number": 1, "text": "..." },
    { "page_number": 2, "text": "..." }
  ]
}

2. Chunking

Split text into 200–500 word chunks for improved retrieval accuracy.

Chunking Rules

Process each page independently.

Use NLP tools (NLTK or spaCy) to split into sentences.

Combine sentences until reaching ~300–400 words.

Preserve metadata: doc_id, page_number, chunk_index.

Chunk Format

{
  "chunk_id": "123_5",
  "doc_id": "123",
  "page_number": 7,
  "text": "chunk text...",
  "word_count": 320
}

3. Embeddings + Vector Store

Convert chunks into embeddings and store them for semantic search.

3.1 Embeddings

Use OpenAI text-embedding-3-large or local Sentence Transformers.

3.2 Vector Database Options

Option

Pros

Cons

FAISS

Free, fast, local

No metadata storage

Pinecone

Hosted, scalable

Monthly cost

Weaviate

Open-source, metadata built-in

More setup

Storage Structure

FAISS index stores vectors.

SQLite/Postgres stores metadata.

4. Retrieval Pipeline

Convert user question → embedding → find relevant chunks → send to LLM.

Steps

User sends question to /query.

Backend embeds the question.

Perform vector similarity search (top‑k = 5–10).

Retrieve chunk metadata.

Build context block for LLM.

Context Assembly

[Chunk 1 — Doc: Bridge Design Notes, Page 7]
text...

[Chunk 2 — Doc: Soil Report, Page 3]
text...

5. LLM Answer Generation

Produce answer, citations, and confidence score.

5.1 Prompt Template

System:

You are an engineering assistant. Use ONLY the provided context.
Cite sources using (Doc, Page). If unsure, say "Not enough information."

User:

Question: {user_question}

5.2 Output Requirements

Answer

Citations (doc + page)

Confidence score (based on similarity + LLM self-rating)

5.3 Response Format

{
  "answer": "...",
  "citations": [
    { "doc": "Bridge Design Notes", "page": 7 },
    { "doc": "Soil Report", "page": 3 }
  ],
  "confidence": 0.87
}

6. Web UI (React)

Simple interface for uploading documents and asking questions.

6.1 Pages

A. Document Upload Page

Drag-and-drop upload.

Show processing stages.

Display list of processed documents.

B. Q&A Page

Input box for questions.

Display answer, confidence score, citations, and chunk previews.

C. Summary Page

Select document → "Generate Summary".

Show LLM-generated summary.

Option to download summary.

6.2 React Components

UploadComponent

DocumentList

QuestionBox

AnswerCard

CitationList

ChunkPreviewModal

7. Implementation Timeline

Phase 1 — Core Backend (Week 1–2)

FastAPI setup

PDF parsing

Chunking

Embeddings

FAISS index

Basic /query endpoint

Phase 2 — OCR + CAD/GIS Support (Week 3)

Add Tesseract/Azure Vision

Add DOCX/TXT support

Phase 3 — Citations + Confidence (Week 4)

Improve prompt

Add similarity-based confidence scoring

Phase 4 — React UI (Week 5–6)

Upload page

Q&A page

Summary page

Phase 5 — Scaling + Optional Cloud (Week 7+)

Pinecone/Weaviate adapter

Authentication

Multi-user support
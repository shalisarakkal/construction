// Mirrors backend/app/schemas.py -- keep in sync manually (no codegen in Phase 4).

export interface ChunkRecord {
  chunk_id: string;
  doc_id: string;
  chunk_type: "njac_section" | "njac_history" | "statute_section" | "statute_history" | "generic";
  citation: string | null;
  section_title: string | null;
  page_number: number | null;
  text: string;
  word_count: number;
  references: string[];
}

export interface DocumentSummary {
  doc_id: string;
  title: string;
  filename: string;
  chunker_used: string;
  chunk_count: number;
  created_at: string;
  is_latest: boolean;
  supersedes_doc_id: string | null;
}

export interface UploadResponse {
  doc_id: string;
  title: string;
  filename: string;
  chunker_used: string;
  chunk_count: number;
  supersedes_doc_id: string | null;
}

export interface UploadAcceptedResponse {
  job_id: string;
  status: "queued";
  filename: string;
}

export type UploadJobStatus = "queued" | "processing" | "done" | "error";

export interface JobStatusResponse {
  job_id: string;
  status: UploadJobStatus;
  filename: string;
  result: UploadResponse | null;
  error: string | null;
}

export interface RetrievedChunk {
  chunk: ChunkRecord;
  doc_title: string;
  score: number;
}

export interface QueryResponse {
  question: string;
  answer: string | null;
  citations: string[];
  confidence: number;
  llm_used: boolean;
  chunks: RetrievedChunk[];
}

export interface DocumentSummaryResponse {
  doc_id: string;
  title: string;
  summary: string;
  chunks_used: number;
  chunks_total: number;
  truncated: boolean;
}

export interface ApiErrorBody {
  detail: string;
}

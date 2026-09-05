import type {
  ApiErrorBody,
  DocumentSummary,
  DocumentSummaryResponse,
  JobStatusResponse,
  QueryResponse,
  UploadAcceptedResponse,
} from "./types";

export const API_BASE = "http://127.0.0.1:8000";

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body.detail) detail = body.detail;
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function uploadDocument(file: File, supersedes?: string): Promise<UploadAcceptedResponse> {
  const form = new FormData();
  form.append("file", file);
  if (supersedes) form.append("supersedes", supersedes);
  return fetch(`${API_BASE}/upload`, { method: "POST", body: form }).then((r) =>
    unwrap<UploadAcceptedResponse>(r)
  );
}

export function getUploadJob(jobId: string): Promise<JobStatusResponse> {
  return fetch(`${API_BASE}/upload/jobs/${jobId}`).then((r) => unwrap<JobStatusResponse>(r));
}

export function listDocuments(includeAll = false): Promise<DocumentSummary[]> {
  const qs = includeAll ? "?include_all=true" : "";
  return fetch(`${API_BASE}/documents${qs}`).then((r) => unwrap<DocumentSummary[]>(r));
}

export function getDocumentVersions(docId: string): Promise<DocumentSummary[]> {
  return fetch(`${API_BASE}/documents/${docId}/versions`).then((r) =>
    unwrap<DocumentSummary[]>(r)
  );
}

export function askQuestion(question: string, topK: number, docIds?: string[]): Promise<QueryResponse> {
  const body: Record<string, unknown> = { question, top_k: topK };
  if (docIds && docIds.length > 0) body.doc_ids = docIds;
  return fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => unwrap<QueryResponse>(r));
}

export function generateSummary(docId: string): Promise<DocumentSummaryResponse> {
  return fetch(`${API_BASE}/documents/${docId}/summary`, { method: "POST" }).then((r) =>
    unwrap<DocumentSummaryResponse>(r)
  );
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, { method: "DELETE" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body.detail) detail = body.detail;
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }
}

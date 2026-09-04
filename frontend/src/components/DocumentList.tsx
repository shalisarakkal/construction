import { useEffect, useState } from "react";
import { deleteDocument, listDocuments, uploadDocument } from "../api";
import { pollJobUntilDone } from "../uploadJob";
import type { DocumentSummary } from "../types";

interface Props {
  onLoaded?: (docs: DocumentSummary[]) => void;
  refreshKey: number;
}

export function DocumentList({ onLoaded, refreshKey }: Props) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [replaceError, setReplaceError] = useState<string | null>(null);
  const [showAllVersions, setShowAllVersions] = useState(false);
  const [localRefresh, setLocalRefresh] = useState(0);

  useEffect(() => {
    setLoading(true);
    listDocuments(showAllVersions)
      .then((d) => {
        setDocs(d);
        setError(null);
        onLoaded?.(d);
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, localRefresh, showAllVersions]);

  async function handleDelete(doc: DocumentSummary) {
    const confirmed = window.confirm(
      `Delete "${doc.title}"? This removes all ${doc.chunk_count} of its chunks from the index. This cannot be undone.`
    );
    if (!confirmed) return;

    setDeletingId(doc.doc_id);
    setDeleteError(null);
    try {
      await deleteDocument(doc.doc_id);
      setLocalRefresh((k) => k + 1);
    } catch (err) {
      setDeleteError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleReplace(doc: DocumentSummary, files: FileList | null) {
    const file = files?.[0];
    if (!file) return;

    setReplacingId(doc.doc_id);
    setReplaceError(null);
    try {
      const accepted = await uploadDocument(file, doc.doc_id);
      const job = await pollJobUntilDone(accepted.job_id);
      if (job.status === "error") {
        setReplaceError(job.error ?? "Processing failed");
      } else {
        setLocalRefresh((k) => k + 1);
      }
    } catch (err) {
      setReplaceError((err as Error).message);
    } finally {
      setReplacingId(null);
    }
  }

  if (loading) return <p className="muted">Loading documents…</p>;
  if (error) return <p className="error-text">Failed to load documents: {error}</p>;

  return (
    <>
      {deleteError && <p className="error-text">Delete failed: {deleteError}</p>}
      {replaceError && <p className="error-text">Replace failed: {replaceError}</p>}
      <label className="version-toggle">
        <input
          type="checkbox"
          checked={showAllVersions}
          onChange={(e) => setShowAllVersions(e.target.checked)}
        />
        {" "}Show superseded versions
      </label>
      {docs.length === 0 ? (
        <p className="muted">No documents processed yet.</p>
      ) : (
        <table className="doc-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Chunker</th>
              <th>Chunks</th>
              <th>Ingested</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.doc_id} className={d.is_latest ? "" : "doc-row-superseded"}>
                <td>
                  {d.title}
                  {!d.is_latest && <span className="badge badge-superseded">superseded</span>}
                </td>
                <td>
                  <span className={`badge badge-${d.chunker_used}`}>{d.chunker_used}</span>
                </td>
                <td>{d.chunk_count}</td>
                <td>{new Date(d.created_at).toLocaleString()}</td>
                <td className="doc-row-actions">
                  {d.is_latest && (
                    <label className="link-button">
                      {replacingId === d.doc_id ? "Replacing…" : "Replace"}
                      <input
                        type="file"
                        className="visually-hidden-input"
                        disabled={replacingId === d.doc_id}
                        onChange={(e) => handleReplace(d, e.target.files)}
                      />
                    </label>
                  )}
                  <button
                    className="link-button danger"
                    onClick={() => handleDelete(d)}
                    disabled={deletingId === d.doc_id}
                  >
                    {deletingId === d.doc_id ? "Deleting…" : "Delete"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

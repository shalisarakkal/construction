import { useEffect, useState } from "react";
import { generateSummary, listDocuments } from "../api";
import type { DocumentSummary, DocumentSummaryResponse } from "../types";

export function SummaryPage() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [summary, setSummary] = useState<DocumentSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then((d) => {
        setDocs(d);
        if (d.length > 0) setSelectedId(d[0].doc_id);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  async function handleGenerate() {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    setSummary(null);
    try {
      const res = await generateSummary(selectedId);
      setSummary(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function handleDownload() {
    if (!summary) return;
    const blob = new Blob([summary.summary], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${summary.title.replace(/\.pdf$/i, "")}-summary.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page">
      <h2>Document summary</h2>

      <div className="summary-controls">
        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} disabled={loading}>
          {docs.length === 0 && <option value="">No documents yet</option>}
          {docs.map((d) => (
            <option key={d.doc_id} value={d.doc_id}>
              {d.title} ({d.chunk_count} chunks)
            </option>
          ))}
        </select>
        <button onClick={handleGenerate} disabled={!selectedId || loading}>
          {loading ? "Generating…" : "Generate Summary"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {summary && (
        <div className="summary-result">
          <h3>{summary.title}</h3>
          {summary.truncated && (
            <p className="warning-text">
              Document has {summary.chunks_total} chunks; summary is based on the first{" "}
              {summary.chunks_used} (word budget cap) — see docs/AllDevFlow.md for the reasoning.
            </p>
          )}
          <pre className="summary-text">{summary.summary}</pre>
          <button onClick={handleDownload}>Download summary (.txt)</button>
        </div>
      )}
    </div>
  );
}

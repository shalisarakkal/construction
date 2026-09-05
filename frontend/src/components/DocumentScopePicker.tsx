import { useEffect, useState } from "react";
import { listDocuments } from "../api";
import type { DocumentSummary } from "../types";

interface Props {
  onChange: (docIds: Set<string>) => void;
}

// Kept separate from QuestionBox (which has no API dependency and its own
// well-covered test suite) rather than folded into it -- see
// docs/AllDevFlow.md's "Scope Q&A to selected document(s)" section.
export function DocumentScopePicker({ onChange }: Props) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((err) => setError((err as Error).message));
  }, []);

  function toggle(docId: string) {
    const next = new Set(selected);
    if (next.has(docId)) next.delete(docId);
    else next.add(docId);
    setSelected(next);
    onChange(next);
  }

  function selectAll() {
    const next = new Set(docs.map((d) => d.doc_id));
    setSelected(next);
    onChange(next);
  }

  function clearAll() {
    const next = new Set<string>();
    setSelected(next);
    onChange(next);
  }

  if (error) return <p className="error-text">Failed to load documents: {error}</p>;
  if (docs.length === 0) return null;

  return (
    <div className="doc-scope-picker">
      <div className="doc-scope-header">
        <span>Scope to specific documents (optional)</span>
        <div className="doc-scope-actions">
          <button type="button" onClick={selectAll}>
            Select all
          </button>
          <button type="button" onClick={clearAll}>
            Clear
          </button>
        </div>
      </div>
      <p className="doc-scope-hint muted">Leave none selected to search all documents.</p>
      <ul className="doc-scope-list">
        {docs.map((d) => (
          <li key={d.doc_id}>
            <label>
              <input
                type="checkbox"
                checked={selected.has(d.doc_id)}
                onChange={() => toggle(d.doc_id)}
              />
              {" "}
              {d.title} ({d.chunk_count} chunks)
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

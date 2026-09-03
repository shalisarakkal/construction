import type { RetrievedChunk } from "../types";

interface Props {
  chunk: RetrievedChunk | null;
  onClose: () => void;
}

export function ChunkPreviewModal({ chunk, onClose }: Props) {
  if (!chunk) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h4>
            {chunk.doc_title}
            {chunk.chunk.citation ? ` — ${chunk.chunk.citation}` : ""}
          </h4>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-meta">
          <span>score {chunk.score.toFixed(3)}</span>
          <span>{chunk.chunk.word_count} words</span>
          {chunk.chunk.page_number != null && <span>page {chunk.chunk.page_number}</span>}
        </div>
        <pre className="modal-text">{chunk.chunk.text}</pre>
        {chunk.chunk.references.length > 0 && (
          <div className="modal-refs">
            <strong>References:</strong> {chunk.chunk.references.join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}

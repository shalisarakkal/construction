import { useState } from "react";
import type { RetrievedChunk } from "../types";
import { ChunkPreviewModal } from "./ChunkPreviewModal";

interface Props {
  chunks: RetrievedChunk[];
}

function snippet(text: string, max = 220): string {
  return text.length > max ? text.slice(0, max).trimEnd() + "…" : text;
}

export function ChunkResultList({ chunks }: Props) {
  const [selected, setSelected] = useState<RetrievedChunk | null>(null);

  if (chunks.length === 0) return null;

  return (
    <div className="chunk-results">
      <h4>Retrieved chunks</h4>
      <ul>
        {chunks.map((rc) => (
          <li key={rc.chunk.chunk_id} className="chunk-result-item">
            <div className="chunk-result-meta">
              <strong>{rc.doc_title}</strong>
              {rc.chunk.citation && <span className="chunk-citation">{rc.chunk.citation}</span>}
              <span className="chunk-score">score {rc.score.toFixed(3)}</span>
            </div>
            <p className="chunk-snippet">{snippet(rc.chunk.text)}</p>
            <button className="link-button" onClick={() => setSelected(rc)}>
              View full chunk
            </button>
          </li>
        ))}
      </ul>
      <ChunkPreviewModal chunk={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

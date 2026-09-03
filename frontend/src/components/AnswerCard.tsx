import type { QueryResponse } from "../types";

// Confidence thresholds are not a guess -- see docs/AllDevFlow.md "Retrieval
// quality" section: measured top-1 FAISS cosine similarity was ~0.82/0.67 for
// genuinely answerable questions vs. ~0.34 for an out-of-scope negative
// control, on real eval-set queries against njac_5_23_12.pdf.
function confidenceLevel(score: number): "high" | "medium" | "low" {
  if (score >= 0.5) return "high";
  if (score >= 0.35) return "medium";
  return "low";
}

interface Props {
  result: QueryResponse;
}

export function AnswerCard({ result }: Props) {
  const level = confidenceLevel(result.confidence);

  return (
    <div className="answer-card">
      <div className="answer-card-header">
        <h3>Answer</h3>
        <span className={`confidence-badge confidence-${level}`}>
          confidence {result.confidence.toFixed(2)}
        </span>
        <span className="llm-badge">{result.llm_used ? "LLM-synthesized" : "retrieval only"}</span>
      </div>

      {level === "low" && (
        <p className="warning-text">
          Low confidence — this question may be out of scope for the ingested documents.
        </p>
      )}

      {result.answer ? (
        <p className="answer-text">{result.answer}</p>
      ) : (
        <p className="muted">
          No LLM configured on the backend — showing raw retrieved passages below instead of a
          synthesized answer.
        </p>
      )}
    </div>
  );
}

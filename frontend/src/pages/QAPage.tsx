import { useState } from "react";
import { askQuestion } from "../api";
import { QuestionBox } from "../components/QuestionBox";
import { DocumentScopePicker } from "../components/DocumentScopePicker";
import { AnswerCard } from "../components/AnswerCard";
import { CitationList } from "../components/CitationList";
import { ChunkResultList } from "../components/ChunkResultList";
import type { QueryResponse } from "../types";

export function QAPage() {
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docIds, setDocIds] = useState<Set<string>>(new Set());

  async function handleAsk(question: string, topK: number) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await askQuestion(question, topK, Array.from(docIds));
      setResult(res);
    } catch (err) {
      setError((err as Error).message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <h2>Ask a question</h2>
      <DocumentScopePicker onChange={setDocIds} />
      <QuestionBox onAsk={handleAsk} disabled={loading} />

      {loading && <p className="loading-text">Generating answer… this can take a couple of minutes.</p>}
      {error && <p className="error-text">{error}</p>}

      {result && (
        <>
          <AnswerCard result={result} />
          <CitationList citations={result.citations} />
          <ChunkResultList chunks={result.chunks} />
        </>
      )}
    </div>
  );
}

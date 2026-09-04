import { useState } from "react";

interface Props {
  onAsk: (question: string, topK: number) => void;
  disabled: boolean;
}

// Configurable via frontend/.env (VITE_DEFAULT_TOP_K) since a higher top-k
// means a longer prompt, which on CPU-backed local LLM inference (see
// docs/AllDevFlow.md's Ollama section) can push a query well past a minute.
const parsedDefaultTopK = Number(import.meta.env.VITE_DEFAULT_TOP_K);
const DEFAULT_TOP_K = Number.isInteger(parsedDefaultTopK) && parsedDefaultTopK > 0 ? parsedDefaultTopK : 5;

export function QuestionBox({ onAsk, disabled }: Props) {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(DEFAULT_TOP_K);

  function submit() {
    if (disabled) return;
    const q = question.trim();
    if (!q) return;
    onAsk(q, topK);
  }

  return (
    <div className="question-box">
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
        }}
        placeholder="Ask a question about the ingested regulations… (Ctrl/Cmd+Enter to submit)"
        rows={3}
        disabled={disabled}
      />
      <div className="question-box-controls">
        <label>
          Top-K:
          <input
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            disabled={disabled}
          />
        </label>
        <button onClick={submit} disabled={disabled || !question.trim()}>
          {disabled ? "Asking…" : "Ask"}
        </button>
      </div>
    </div>
  );
}

import { useState } from "react";

interface Props {
  onAsk: (question: string, topK: number) => void;
  disabled: boolean;
}

export function QuestionBox({ onAsk, disabled }: Props) {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);

  function submit() {
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
          />
        </label>
        <button onClick={submit} disabled={disabled || !question.trim()}>
          {disabled ? "Asking…" : "Ask"}
        </button>
      </div>
    </div>
  );
}

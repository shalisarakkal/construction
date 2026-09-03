import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { QueryResponse } from "../types";
import { AnswerCard } from "./AnswerCard";

function makeResult(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    question: "What is required?",
    answer: "You need a permit.",
    citations: [],
    confidence: 0.6,
    llm_used: true,
    chunks: [],
    ...overrides,
  };
}

describe("AnswerCard", () => {
  it("shows the synthesized answer and LLM badge when an answer is present", () => {
    render(<AnswerCard result={makeResult({ answer: "You need a permit.", llm_used: true })} />);

    expect(screen.getByText("You need a permit.")).toBeInTheDocument();
    expect(screen.getByText("LLM-synthesized")).toBeInTheDocument();
  });

  it("shows a retrieval-only fallback message when there is no answer", () => {
    render(<AnswerCard result={makeResult({ answer: null, llm_used: false })} />);

    expect(screen.getByText(/no llm configured on the backend/i)).toBeInTheDocument();
    expect(screen.getByText("retrieval only")).toBeInTheDocument();
  });

  it.each([
    [0.9, "confidence-high"],
    [0.5, "confidence-high"],
    [0.4, "confidence-medium"],
    [0.35, "confidence-medium"],
    [0.2, "confidence-low"],
  ])("classifies confidence %f as %s", (confidence, expectedClass) => {
    render(<AnswerCard result={makeResult({ confidence })} />);

    expect(screen.getByText(`confidence ${confidence.toFixed(2)}`)).toHaveClass(expectedClass);
  });

  it("shows a low-confidence warning only when confidence is below 0.35", () => {
    const { rerender } = render(<AnswerCard result={makeResult({ confidence: 0.2 })} />);
    expect(screen.getByText(/may be out of scope/i)).toBeInTheDocument();

    rerender(<AnswerCard result={makeResult({ confidence: 0.5 })} />);
    expect(screen.queryByText(/may be out of scope/i)).not.toBeInTheDocument();
  });
});

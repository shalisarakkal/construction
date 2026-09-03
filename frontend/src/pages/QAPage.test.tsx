import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { QueryResponse } from "../types";
import { QAPage } from "./QAPage";

vi.mock("../api");

function makeResult(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    question: "first question",
    answer: "First answer.",
    citations: ["doc.pdf — page 1"],
    confidence: 0.6,
    llm_used: true,
    chunks: [],
    ...overrides,
  };
}

async function askQuestion(user: ReturnType<typeof userEvent.setup>, question: string) {
  const textarea = screen.getByPlaceholderText(/ask a question/i);
  await user.clear(textarea);
  await user.type(textarea, question);
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => {
  vi.mocked(api.askQuestion).mockReset();
});

describe("QAPage", () => {
  it("renders the answer, citations, and chunks after a successful query", async () => {
    const user = userEvent.setup();
    vi.mocked(api.askQuestion).mockResolvedValue(makeResult());
    render(<QAPage />);

    await askQuestion(user, "first question");

    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());
    expect(screen.getByText("doc.pdf — page 1")).toBeInTheDocument();
  });

  it("shows a loading message while a query is in flight", async () => {
    const user = userEvent.setup();
    let resolvePromise: (value: QueryResponse) => void = () => {};
    vi.mocked(api.askQuestion).mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      })
    );
    render(<QAPage />);

    await askQuestion(user, "first question");

    expect(screen.getByText(/generating answer/i)).toBeInTheDocument();
    resolvePromise(makeResult());
    await waitFor(() => expect(screen.queryByText(/generating answer/i)).not.toBeInTheDocument());
  });

  it("clears the previous answer immediately when a new question is submitted, before the new result arrives", async () => {
    const user = userEvent.setup();
    vi.mocked(api.askQuestion).mockResolvedValueOnce(makeResult({ answer: "First answer." }));
    render(<QAPage />);

    await askQuestion(user, "first question");
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    // Second query never resolves during this assertion window -- the point
    // is to check state immediately after submit, not after completion.
    vi.mocked(api.askQuestion).mockReturnValue(new Promise(() => {}));
    await askQuestion(user, "second question");

    expect(screen.queryByText("First answer.")).not.toBeInTheDocument();
    expect(screen.getByText(/generating answer/i)).toBeInTheDocument();
  });

  it("shows an error message and clears any previous result when the query fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.askQuestion).mockResolvedValueOnce(makeResult({ answer: "First answer." }));
    render(<QAPage />);
    await askQuestion(user, "first question");
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    vi.mocked(api.askQuestion).mockRejectedValueOnce(new Error("Internal Server Error"));
    await askQuestion(user, "second question");

    await waitFor(() => expect(screen.getByText("Internal Server Error")).toBeInTheDocument());
    expect(screen.queryByText("First answer.")).not.toBeInTheDocument();
  });
});

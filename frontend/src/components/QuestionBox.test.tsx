import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QuestionBox } from "./QuestionBox";

// Must match frontend/.env's VITE_DEFAULT_TOP_K -- Vite loads that file in
// test mode too, so the component really does default to this value here.
const DEFAULT_TOP_K = 3;

describe("QuestionBox", () => {
  it("submits the trimmed question and top-k on button click", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(<QuestionBox onAsk={onAsk} disabled={false} />);

    await user.type(screen.getByPlaceholderText(/ask a question/i), "  What permits are required?  ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onAsk).toHaveBeenCalledWith("What permits are required?", DEFAULT_TOP_K);
  });

  it("does not submit an empty or whitespace-only question", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(<QuestionBox onAsk={onAsk} disabled={false} />);

    await user.type(screen.getByPlaceholderText(/ask a question/i), "   ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onAsk).not.toHaveBeenCalled();
  });

  it("submits on Ctrl+Enter", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(<QuestionBox onAsk={onAsk} disabled={false} />);

    await user.type(screen.getByPlaceholderText(/ask a question/i), "Permit question{Control>}{Enter}{/Control}");

    expect(onAsk).toHaveBeenCalledWith("Permit question", DEFAULT_TOP_K);
  });

  it("respects a custom top-k value", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(<QuestionBox onAsk={onAsk} disabled={false} />);

    await user.type(screen.getByPlaceholderText(/ask a question/i), "A question");
    const topKInput = screen.getByLabelText(/top-k/i);
    await user.clear(topKInput);
    await user.type(topKInput, "7");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onAsk).toHaveBeenCalledWith("A question", 7);
  });

  it("disables the input and shows 'Asking…' while disabled", () => {
    render(<QuestionBox onAsk={vi.fn()} disabled={true} />);

    expect(screen.getByRole("button", { name: "Asking…" })).toBeDisabled();
  });

  it("initializes the Top-K field from VITE_DEFAULT_TOP_K", () => {
    render(<QuestionBox onAsk={vi.fn()} disabled={false} />);

    expect(screen.getByLabelText(/top-k/i)).toHaveValue(DEFAULT_TOP_K);
  });
});

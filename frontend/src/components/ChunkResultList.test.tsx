import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { RetrievedChunk } from "../types";
import { ChunkResultList } from "./ChunkResultList";

function makeChunk(overrides: Partial<RetrievedChunk> = {}): RetrievedChunk {
  return {
    doc_title: "njac_5_23_1.pdf",
    score: 0.555,
    chunk: {
      chunk_id: "c1",
      doc_id: "doc1",
      chunk_type: "generic",
      citation: "N.J.A.C. 5:23-1.1",
      section_title: null,
      page_number: 1,
      text: "A".repeat(300),
      word_count: 50,
      references: [],
    },
    ...overrides,
  };
}

describe("ChunkResultList", () => {
  it("renders nothing when there are no chunks", () => {
    const { container } = render(<ChunkResultList chunks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("truncates a long chunk snippet with an ellipsis", () => {
    render(<ChunkResultList chunks={[makeChunk()]} />);

    const snippet = screen.getByText(/A+…$/);
    expect(snippet.textContent!.length).toBeLessThan(300);
  });

  it("opens the full-chunk modal on click and closes it via the overlay", async () => {
    const user = userEvent.setup();
    // Long enough that the snippet truncates before this marker, so it only
    // ever appears once the modal shows the full, untruncated text.
    const fullText = "A".repeat(250) + " END_MARKER";
    render(<ChunkResultList chunks={[makeChunk({ chunk: { ...makeChunk().chunk, text: fullText } })]} />);

    expect(screen.queryByText(/END_MARKER/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /view full chunk/i }));
    expect(screen.getByText(/END_MARKER/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByText(/END_MARKER/)).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CitationList } from "./CitationList";

describe("CitationList", () => {
  it("renders nothing when there are no citations", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders each citation as a list item", () => {
    render(<CitationList citations={["doc_a.pdf — page 1", "doc_b.pdf — page 2"]} />);

    expect(screen.getByText("doc_a.pdf — page 1")).toBeInTheDocument();
    expect(screen.getByText("doc_b.pdf — page 2")).toBeInTheDocument();
  });
});

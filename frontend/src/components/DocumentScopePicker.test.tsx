import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { DocumentSummary } from "../types";
import { DocumentScopePicker } from "./DocumentScopePicker";

vi.mock("../api");

function makeDoc(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    doc_id: "doc1",
    title: "njac_5_23_1.pdf",
    filename: "njac_5_23_1.pdf",
    chunker_used: "njac",
    chunk_count: 12,
    created_at: "2026-09-03T00:00:00Z",
    is_latest: true,
    supersedes_doc_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.listDocuments).mockReset();
});

describe("DocumentScopePicker", () => {
  it("renders nothing when there are no documents", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([]);
    const { container } = render(<DocumentScopePicker onChange={vi.fn()} />);

    await waitFor(() => expect(api.listDocuments).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a checkbox per document", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([
      makeDoc({ doc_id: "doc1", title: "njac_5_23_1.pdf" }),
      makeDoc({ doc_id: "doc2", title: "njac_5_23_2.pdf" }),
    ]);
    render(<DocumentScopePicker onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(2));
    expect(screen.getByText(/njac_5_23_1\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/njac_5_23_2\.pdf/)).toBeInTheDocument();
  });

  it("calls onChange with the toggled document's id", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc({ doc_id: "doc1" })]);
    const onChange = vi.fn();
    render(<DocumentScopePicker onChange={onChange} />);

    await waitFor(() => expect(screen.getByRole("checkbox")).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenLastCalledWith(new Set(["doc1"]));

    await user.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenLastCalledWith(new Set());
  });

  it("'Select all' selects every document and 'Clear' deselects them", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue([
      makeDoc({ doc_id: "doc1" }),
      makeDoc({ doc_id: "doc2" }),
    ]);
    const onChange = vi.fn();
    render(<DocumentScopePicker onChange={onChange} />);

    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(2));

    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(onChange).toHaveBeenLastCalledWith(new Set(["doc1", "doc2"]));

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenLastCalledWith(new Set());
  });

  it("shows an error message when the document list fails to load", async () => {
    vi.mocked(api.listDocuments).mockRejectedValue(new Error("network down"));
    render(<DocumentScopePicker onChange={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/failed to load documents: network down/i)).toBeInTheDocument()
    );
  });
});

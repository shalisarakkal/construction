import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { DocumentSummary, DocumentSummaryResponse } from "../types";
import { SummaryPage } from "./SummaryPage";

vi.mock("../api");

function makeDocs(): DocumentSummary[] {
  return [
    {
      doc_id: "doc1",
      title: "njac_5_23_1.pdf",
      filename: "njac_5_23_1.pdf",
      chunker_used: "njac",
      chunk_count: 12,
      created_at: "2026-09-03T00:00:00Z",
      is_latest: true,
      supersedes_doc_id: null,
    },
  ];
}

function makeSummary(overrides: Partial<DocumentSummaryResponse> = {}): DocumentSummaryResponse {
  return {
    doc_id: "doc1",
    title: "njac_5_23_1.pdf",
    summary: "This document covers fire door rating requirements.",
    chunks_used: 12,
    chunks_total: 12,
    truncated: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.listDocuments).mockReset();
  vi.mocked(api.generateSummary).mockReset();
  vi.mocked(api.listDocuments).mockResolvedValue(makeDocs());
});

describe("SummaryPage", () => {
  it("shows the document title as a heading even when the summary is not truncated", async () => {
    const user = userEvent.setup();
    vi.mocked(api.generateSummary).mockResolvedValue(makeSummary({ truncated: false }));
    render(<SummaryPage />);

    await waitFor(() => expect(screen.getByRole("option", { name: /njac_5_23_1\.pdf/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Generate Summary" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 3, name: "njac_5_23_1.pdf" })).toBeInTheDocument()
    );
    expect(screen.queryByText(/word budget cap/i)).not.toBeInTheDocument();
  });

  it("shows the truncation warning when the summary was truncated", async () => {
    const user = userEvent.setup();
    vi.mocked(api.generateSummary).mockResolvedValue(
      makeSummary({ truncated: true, chunks_used: 21, chunks_total: 1141 })
    );
    render(<SummaryPage />);

    await waitFor(() => expect(screen.getByRole("option", { name: /njac_5_23_1\.pdf/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Generate Summary" }));

    await waitFor(() => expect(screen.getByText(/word budget cap/i)).toBeInTheDocument());
    expect(screen.getByText(/has 1141 chunks/)).toBeInTheDocument();
    expect(screen.getByText(/first.*21/)).toBeInTheDocument();
  });

  it("disables the document selector while a summary is being generated", async () => {
    const user = userEvent.setup();
    vi.mocked(api.generateSummary).mockReturnValue(new Promise(() => {}));
    render(<SummaryPage />);

    await waitFor(() => expect(screen.getByRole("option", { name: /njac_5_23_1\.pdf/ })).toBeInTheDocument());
    const select = screen.getByRole("combobox");
    expect(select).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Generate Summary" }));

    expect(select).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generating…" })).toBeDisabled();
  });

  it("shows an error message when summary generation fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.generateSummary).mockRejectedValue(new Error("Summary generation requires the LLM provider"));
    render(<SummaryPage />);

    await waitFor(() => expect(screen.getByRole("option", { name: /njac_5_23_1\.pdf/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Generate Summary" }));

    await waitFor(() =>
      expect(screen.getByText("Summary generation requires the LLM provider")).toBeInTheDocument()
    );
  });
});

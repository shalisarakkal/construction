import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { DocumentSummary, UploadResponse } from "../types";
import { DocumentList } from "./DocumentList";

vi.mock("../api");

function makeFile(name: string, content = "content") {
  return new File([content], name, { type: "text/plain" });
}

function getReplaceInput(): HTMLInputElement {
  // The "Replace" label wraps a visually-hidden file input.
  return screen.getByText("Replace").parentElement!.querySelector('input[type="file"]')!;
}

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

function makeUploadResponse(overrides: Partial<UploadResponse> = {}): UploadResponse {
  return {
    doc_id: "doc2",
    title: "v2.txt",
    filename: "v2.txt",
    chunker_used: "generic",
    chunk_count: 1,
    supersedes_doc_id: "doc1",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.listDocuments).mockReset();
  vi.mocked(api.deleteDocument).mockReset();
  vi.mocked(api.uploadDocument).mockReset();
  vi.mocked(api.getUploadJob).mockReset();
});

describe("DocumentList", () => {
  it("shows a loading message, then the document table", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    render(<DocumentList refreshKey={0} />);

    expect(screen.getByText(/loading documents/i)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());
  });

  it("shows an empty state when there are no documents", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([]);
    render(<DocumentList refreshKey={0} />);

    await waitFor(() => expect(screen.getByText(/no documents processed yet/i)).toBeInTheDocument());
  });

  it("shows an error message when the initial load fails", async () => {
    vi.mocked(api.listDocuments).mockRejectedValue(new Error("network down"));
    render(<DocumentList refreshKey={0} />);

    await waitFor(() =>
      expect(screen.getByText(/failed to load documents: network down/i)).toBeInTheDocument()
    );
  });

  it("re-fetches with include_all=true when 'Show superseded versions' is checked", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    const user = userEvent.setup();
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    expect(api.listDocuments).toHaveBeenLastCalledWith(false);

    await user.click(screen.getByLabelText(/show superseded versions/i));

    await waitFor(() => expect(api.listDocuments).toHaveBeenLastCalledWith(true));
  });

  it("deletes a document after confirmation and refreshes the list", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    vi.mocked(api.deleteDocument).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith("doc1"));
    // localRefresh bump triggers a second listDocuments call.
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(2));
  });

  it("does not delete when the confirmation dialog is cancelled", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(api.deleteDocument).not.toHaveBeenCalled();
  });

  it("shows a delete error message when deletion fails", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    vi.mocked(api.deleteDocument).mockRejectedValue(new Error("locked"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByText(/delete failed: locked/i)).toBeInTheDocument());
  });

  it("marks a superseded document with a badge and hides its Replace action", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc({ is_latest: false })]);
    render(<DocumentList refreshKey={0} />);

    await waitFor(() => expect(screen.getByText("superseded")).toBeInTheDocument());
    expect(screen.queryByText("Replace")).not.toBeInTheDocument();
  });

  it("waits for the replace job to finish before refreshing the list", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    vi.mocked(api.uploadDocument).mockResolvedValue({ job_id: "job1", status: "queued", filename: "v2.txt" });
    vi.mocked(api.getUploadJob).mockResolvedValue({
      job_id: "job1",
      status: "done",
      filename: "v2.txt",
      result: makeUploadResponse(),
      error: null,
    });
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    await user.upload(getReplaceInput(), makeFile("v2.txt"));

    await waitFor(() => expect(screen.getByText("Replace")).toBeInTheDocument());
    expect(api.uploadDocument).toHaveBeenCalledWith(expect.any(File), "doc1");
    expect(api.getUploadJob).toHaveBeenCalledWith("job1");
    // localRefresh bump triggers a second listDocuments call, only after the job resolved.
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/replace failed/i)).not.toBeInTheDocument();
  });

  it("shows a replace error when the background job fails, without refreshing the list", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listDocuments).mockResolvedValue([makeDoc()]);
    vi.mocked(api.uploadDocument).mockResolvedValue({ job_id: "job1", status: "queued", filename: "v2.txt" });
    vi.mocked(api.getUploadJob).mockResolvedValue({
      job_id: "job1",
      status: "error",
      filename: "v2.txt",
      result: null,
      error: "No extractable text found in document",
    });
    render(<DocumentList refreshKey={0} />);
    await waitFor(() => expect(screen.getByText("njac_5_23_1.pdf")).toBeInTheDocument());

    await user.upload(getReplaceInput(), makeFile("v2.txt"));

    await waitFor(() =>
      expect(screen.getByText(/replace failed: no extractable text found in document/i)).toBeInTheDocument()
    );
    expect(api.listDocuments).toHaveBeenCalledTimes(1);
  });
});

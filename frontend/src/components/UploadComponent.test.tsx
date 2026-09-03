import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { UploadResponse } from "../types";
import { UploadComponent } from "./UploadComponent";

vi.mock("../api");

function makeFile(name: string, content = "content") {
  return new File([content], name, { type: "text/plain" });
}

function makeUploadResponse(overrides: Partial<UploadResponse> = {}): UploadResponse {
  return {
    doc_id: "doc1",
    title: "file.txt",
    filename: "file.txt",
    chunker_used: "generic",
    chunk_count: 1,
    supersedes_doc_id: null,
    ...overrides,
  };
}

function getFileInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[type="file"]')!;
}

beforeEach(() => {
  vi.mocked(api.uploadDocument).mockReset();
});

describe("UploadComponent", () => {
  it("shows 'Done' with chunk info after a successful upload", async () => {
    const user = userEvent.setup();
    vi.mocked(api.uploadDocument).mockResolvedValue(
      makeUploadResponse({ chunk_count: 3, chunker_used: "njac" })
    );
    const { container } = render(<UploadComponent onUploaded={vi.fn()} />);

    await user.upload(getFileInput(container), makeFile("njac_5_23_1.pdf"));

    await waitFor(() => expect(screen.getByText(/done — 3 chunks \(njac\)/i)).toBeInTheDocument());
  });

  it("shows an error with the backend's message when upload fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.uploadDocument).mockRejectedValue(
      new Error("This file was already ingested as 'a.txt' (doc_id=abc123)")
    );
    const { container } = render(<UploadComponent onUploaded={vi.fn()} />);

    await user.upload(getFileInput(container), makeFile("a.txt"));

    await waitFor(() =>
      expect(screen.getByText(/error — this file was already ingested/i)).toBeInTheDocument()
    );
  });

  it("replaces the previous batch's entries instead of accumulating them across uploads", async () => {
    const user = userEvent.setup();
    vi.mocked(api.uploadDocument).mockRejectedValueOnce(new Error("Duplicate of doc A"));
    const { container } = render(<UploadComponent onUploaded={vi.fn()} />);

    await user.upload(getFileInput(container), makeFile("doc_a.txt"));
    await waitFor(() => expect(screen.getByText(/error — duplicate of doc a/i)).toBeInTheDocument());

    vi.mocked(api.uploadDocument).mockRejectedValueOnce(new Error("Duplicate of doc B"));
    await user.upload(getFileInput(container), makeFile("doc_b.txt"));

    await waitFor(() => expect(screen.getByText(/error — duplicate of doc b/i)).toBeInTheDocument());
    // The first batch's error entry must be gone, not stacked underneath.
    expect(screen.queryByText("doc_a.txt")).not.toBeInTheDocument();
    expect(screen.queryByText(/duplicate of doc a/i)).not.toBeInTheDocument();
  });

  it("calls onUploaded after a successful upload but not after a failed one", async () => {
    const user = userEvent.setup();
    const onUploaded = vi.fn();
    vi.mocked(api.uploadDocument).mockRejectedValueOnce(new Error("boom"));
    const { container } = render(<UploadComponent onUploaded={onUploaded} />);

    await user.upload(getFileInput(container), makeFile("bad.txt"));
    await waitFor(() => expect(screen.getByText(/error — boom/i)).toBeInTheDocument());
    expect(onUploaded).not.toHaveBeenCalled();

    vi.mocked(api.uploadDocument).mockResolvedValueOnce(makeUploadResponse());
    await user.upload(getFileInput(container), makeFile("good.txt"));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
  });
});

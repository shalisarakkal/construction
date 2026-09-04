import { useId, useState } from "react";
import { getUploadJob, uploadDocument } from "../api";
import type { JobStatusResponse } from "../types";

type FileStatus = "queued" | "uploading" | "processing" | "done" | "error";

interface FileEntry {
  key: string;
  name: string;
  status: FileStatus;
  detail?: string;
}

interface Props {
  onUploaded: () => void;
}

const POLL_INTERVAL_MS = 800;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// /upload now just enqueues a background ingest job (the actual PDF
// parsing + embedding can take seconds to minutes) and returns a job_id
// immediately -- poll /upload/jobs/{job_id} until it leaves the
// queued/processing states.
async function pollJobUntilDone(jobId: string): Promise<JobStatusResponse> {
  for (;;) {
    const job = await getUploadJob(jobId);
    if (job.status === "done" || job.status === "error") return job;
    await sleep(POLL_INTERVAL_MS);
  }
}

export function UploadComponent({ onUploaded }: Props) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const inputId = useId();

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const list = Array.from(files);

    const newEntries: FileEntry[] = list.map((f) => ({
      key: `${f.name}-${Date.now()}-${Math.random()}`,
      name: f.name,
      status: "queued",
    }));
    setEntries(newEntries);

    for (let i = 0; i < list.length; i++) {
      const file = list[i];
      const key = newEntries[i].key;
      setEntries((prev) =>
        prev.map((e) => (e.key === key ? { ...e, status: "uploading" } : e))
      );
      try {
        const accepted = await uploadDocument(file);
        setEntries((prev) =>
          prev.map((e) => (e.key === key ? { ...e, status: "processing" } : e))
        );

        const job = await pollJobUntilDone(accepted.job_id);
        if (job.status === "done" && job.result) {
          const result = job.result;
          setEntries((prev) =>
            prev.map((e) =>
              e.key === key
                ? { ...e, status: "done", detail: `${result.chunk_count} chunks (${result.chunker_used})` }
                : e
            )
          );
          onUploaded();
        } else {
          setEntries((prev) =>
            prev.map((e) =>
              e.key === key
                ? { ...e, status: "error", detail: job.error ?? "Processing failed" }
                : e
            )
          );
        }
      } catch (err) {
        setEntries((prev) =>
          prev.map((e) =>
            e.key === key
              ? { ...e, status: "error", detail: (err as Error).message }
              : e
          )
        );
      }
    }
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        className={`dropzone ${dragActive ? "dropzone-active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <p>Drag & drop PDF, DOCX, or TXT files here, or click to choose files</p>
        <p className="dropzone-hint">
          Scanned/image-only PDF pages are OCR'd automatically
        </p>
        <input
          id={inputId}
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          className="visually-hidden-input"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>

      {entries.length > 0 && (
        <ul className="upload-list">
          {entries.map((e) => (
            <li key={e.key} className={`upload-item upload-item-${e.status}`}>
              <span className="upload-item-name">{e.name}</span>
              <span className="upload-item-status">
                {e.status === "queued" && "Queued"}
                {e.status === "uploading" && "Uploading…"}
                {e.status === "processing" && "Processing…"}
                {e.status === "done" && `Done — ${e.detail}`}
                {e.status === "error" && `Error — ${e.detail}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

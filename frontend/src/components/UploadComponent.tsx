import { useId, useState } from "react";
import { uploadDocument } from "../api";

type FileStatus = "queued" | "uploading" | "done" | "error";

interface FileEntry {
  key: string;
  name: string;
  status: FileStatus;
  detail?: string;
}

interface Props {
  onUploaded: () => void;
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
        const result = await uploadDocument(file);
        setEntries((prev) =>
          prev.map((e) =>
            e.key === key
              ? { ...e, status: "done", detail: `${result.chunk_count} chunks (${result.chunker_used})` }
              : e
          )
        );
        onUploaded();
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
                {e.status === "uploading" && "Processing…"}
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

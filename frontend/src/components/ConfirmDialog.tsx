import { useEffect } from "react";

interface Props {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

// In-app replacement for window.confirm() on destructive actions -- see
// docs/AllDevFlow.md's visual QA pass, 2026-09-04: native confirm() is a
// defensible choice for a destructive action (synchronous, can't be styled
// into a misclickable state) but doesn't respect the app's theme/dark mode.
// Reuses the same .modal/.modal-overlay pattern as ChunkPreviewModal for
// visual consistency.
export function ConfirmDialog({ title, message, confirmLabel = "Confirm", danger, onConfirm, onCancel }: Props) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onCancel]);

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h4 id="confirm-dialog-title">{title}</h4>
        </div>
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button className="confirm-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className={`confirm-button${danger ? " danger" : ""}`} onClick={onConfirm} autoFocus>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

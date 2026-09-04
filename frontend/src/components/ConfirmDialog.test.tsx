import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders the title, message, and confirm label", () => {
    render(
      <ConfirmDialog
        title="Delete document"
        message='Delete "a.pdf"? This cannot be undone.'
        confirmLabel="Delete"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete document")).toBeInTheDocument();
    expect(screen.getByText(/delete "a\.pdf"/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog title="Delete" message="Sure?" onConfirm={onConfirm} onCancel={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the Cancel button is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog title="Delete" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when clicking the overlay outside the dialog", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { container } = render(
      <ConfirmDialog title="Delete" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />
    );

    await user.click(container.querySelector(".modal-overlay")!);

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not call onCancel when clicking inside the dialog itself", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog title="Delete" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />);

    await user.click(screen.getByText("Sure?"));

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("calls onCancel on Escape", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog title="Delete" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />);

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("applies the danger style to the confirm button when danger is set", () => {
    render(<ConfirmDialog title="Delete" message="Sure?" danger onConfirm={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Confirm" })).toHaveClass("confirm-button", "danger");
  });
});

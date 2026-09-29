import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { ConfirmTransition } from "./ConfirmTransition";
import { LifecycleRefusal } from "./lifecycle";

describe("ConfirmTransition", () => {
  it("asks in place, focusing the confirm, and confirms by keyboard", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderWithProviders(
      <ConfirmTransition
        question="Build revision A?"
        confirmLabel="Build it"
        pending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    const user = userEvent.setup();

    const group = screen.getByRole("group", { name: "Build revision A?" });
    const confirm = within(group).getByRole("button", { name: "Build it" });
    expect(confirm).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("backs out on Escape and with the button", async () => {
    const onCancel = vi.fn();
    renderWithProviders(
      <ConfirmTransition
        question="Cancel the reservation on revision A?"
        confirmLabel="Cancel it"
        pending={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    const user = userEvent.setup();

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Never mind" }));
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("shows a refusal in the reader's language, from its code", () => {
    renderWithProviders(
      <ConfirmTransition
        question="Build revision A?"
        confirmLabel="Build it"
        pending={false}
        error={new LifecycleRefusal(409, "transition_not_allowed", "build", "draft")}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This revision is Draft, so it can't build.",
    );
  });
});

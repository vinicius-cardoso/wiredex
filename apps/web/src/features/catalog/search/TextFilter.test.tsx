import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { anAttribute } from "../../../test/server";
import { TextFilter } from "./TextFilter";

const notes = anAttribute({ key: "notes", label: "Notes", kind: "text", unit: null, options: [] });

/** A stateful host, so the controlled input accumulates keystrokes as it does in the page. */
function Host({ onChange }: { onChange: (value: unknown) => void }) {
  const [filter, setFilter] = useState<{ type: "text"; key: string; text: string } | undefined>(
    undefined,
  );
  return (
    <TextFilter
      attribute={notes}
      filter={filter}
      onChange={(next) => {
        setFilter(next ?? undefined);
        onChange(next);
      }}
    />
  );
}

describe("TextFilter", () => {
  it("reports the fragment as it is typed", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Host onChange={onChange} />);

    await userEvent.setup().type(screen.getByRole("textbox", { name: "Notes" }), "hi");

    expect(onChange).toHaveBeenLastCalledWith({ type: "text", key: "notes", text: "hi" });
  });

  it("drops the filter when the box is cleared", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <TextFilter
        attribute={notes}
        filter={{ type: "text", key: "notes", text: "hi" }}
        onChange={onChange}
      />,
    );

    await userEvent.setup().clear(screen.getByRole("textbox", { name: "Notes" }));

    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

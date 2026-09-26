import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { anAttribute } from "../../../test/server";
import { BoolFilter } from "./BoolFilter";

const rohs = anAttribute({ key: "rohs", label: "RoHS", kind: "bool", unit: null, options: [] });

describe("BoolFilter", () => {
  it("defaults to 'any' when no choice is set", () => {
    renderWithProviders(<BoolFilter attribute={rohs} filter={undefined} onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: "Any" })).toBeChecked();
  });

  it("reports true when yes is chosen", async () => {
    const onChange = vi.fn();
    renderWithProviders(<BoolFilter attribute={rohs} filter={undefined} onChange={onChange} />);

    await userEvent.setup().click(screen.getByRole("radio", { name: "Yes" }));

    expect(onChange).toHaveBeenLastCalledWith({ type: "bool", key: "rohs", value: true });
  });

  it("drops the filter when 'any' is chosen again", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <BoolFilter
        attribute={rohs}
        filter={{ type: "bool", key: "rohs", value: false }}
        onChange={onChange}
      />,
    );

    expect(screen.getByRole("radio", { name: "No" })).toBeChecked();
    await userEvent.setup().click(screen.getByRole("radio", { name: "Any" }));

    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

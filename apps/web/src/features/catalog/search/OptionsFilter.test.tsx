import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { anAttribute } from "../../../test/server";
import { OptionsFilter } from "./OptionsFilter";

const pkg = anAttribute({
  key: "package",
  label: "Package",
  kind: "enum",
  unit: null,
  options: ["0805", "0603", "0402"],
});

type Options = { type: "options"; key: string; options: string[] };

/** A stateful host, so a second tick sees the first, as the page's state does. */
function Host({ onChange }: { onChange: (value: unknown) => void }) {
  const [filter, setFilter] = useState<Options | undefined>(undefined);
  return (
    <OptionsFilter
      attribute={pkg}
      filter={filter}
      counts={undefined}
      onChange={(next) => {
        setFilter(next ?? undefined);
        onChange(next);
      }}
    />
  );
}

describe("OptionsFilter", () => {
  it("shows each option with how many parts hold it", () => {
    renderWithProviders(
      <OptionsFilter
        attribute={pkg}
        filter={undefined}
        onChange={vi.fn()}
        counts={[
          { option: "0805", count: 12 },
          { option: "0603", count: 3 },
        ]}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "0805 (12)" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "0603 (3)" })).toBeInTheDocument();
    // An option no part holds still shows, at zero.
    expect(screen.getByRole("checkbox", { name: "0402 (0)" })).toBeInTheDocument();
  });

  it("reports the ticked options in the schema's order", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Host onChange={onChange} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "0603 (0)" }));
    await user.click(screen.getByRole("checkbox", { name: "0805 (0)" }));

    expect(onChange).toHaveBeenLastCalledWith({
      type: "options",
      key: "package",
      options: ["0805", "0603"],
    });
  });

  it("drops the filter when the last option is unticked", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <OptionsFilter
        attribute={pkg}
        filter={{ type: "options", key: "package", options: ["0805"] }}
        onChange={onChange}
        counts={undefined}
      />,
    );

    await userEvent.setup().click(screen.getByRole("checkbox", { name: "0805 (0)" }));

    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

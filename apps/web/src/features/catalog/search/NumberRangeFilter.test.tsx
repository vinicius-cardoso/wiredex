import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { anAttribute } from "../../../test/server";
import { NumberRangeFilter } from "./NumberRangeFilter";

const resistance = anAttribute({
  key: "resistance",
  label: "Resistance",
  kind: "number",
  unit: "Ω",
});

type Range = { type: "range"; key: string; minimum: string | null; maximum: string | null };

/** A stateful host, so the controlled bounds accumulate keystrokes as in the page. */
function Host({ onChange }: { onChange: (value: unknown) => void }) {
  const [filter, setFilter] = useState<Range | undefined>(undefined);
  return (
    <NumberRangeFilter
      attribute={resistance}
      filter={filter}
      onChange={(next) => {
        setFilter(next ?? undefined);
        onChange(next);
      }}
    />
  );
}

describe("NumberRangeFilter", () => {
  it("reports a range as the bounds are typed", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Host onChange={onChange} />);

    await userEvent
      .setup()
      .type(screen.getByRole("textbox", { name: "Resistance at least" }), "1k");

    expect(onChange).toHaveBeenLastCalledWith({
      type: "range",
      key: "resistance",
      minimum: "1k",
      maximum: null,
    });
  });

  it("shows the normalized value as it is typed", async () => {
    renderWithProviders(
      <NumberRangeFilter
        attribute={resistance}
        filter={{ type: "range", key: "resistance", minimum: "4k7", maximum: null }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("= 4.7kΩ")).toBeInTheDocument();
  });

  it("drops the filter when both bounds are cleared", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <NumberRangeFilter
        attribute={resistance}
        filter={{ type: "range", key: "resistance", minimum: "1k", maximum: null }}
        onChange={onChange}
      />,
    );

    await userEvent.setup().clear(screen.getByRole("textbox", { name: "Resistance at least" }));

    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("shows the refusal the API gave next to the field", () => {
    renderWithProviders(
      <NumberRangeFilter
        attribute={resistance}
        filter={{ type: "range", key: "resistance", minimum: "10k", maximum: "1k" }}
        onChange={vi.fn()}
        refusal="filter resistance: the minimum is above the maximum"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("the minimum is above the maximum");
  });
});

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FacetsResponse } from "@wiredex/api-client";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { aCategory, anAttribute } from "../../../test/server";
import { FilterPanel } from "./FilterPanel";
import { emptyQuery, type PartQuery } from "./searchParams";

const passives = aCategory({ name: "Passives", child_count: 1 });
const resistors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  parent_id: passives.id,
  name: "Resistors",
});
const resistance = anAttribute({
  category_id: resistors.id,
  key: "resistance",
  label: "Resistance",
  kind: "number",
  unit: "Ω",
});

const facets: FacetsResponse = { enums: {}, bools: {}, numbers: {} };

function renderPanel(query: PartQuery, onChange = vi.fn()) {
  renderWithProviders(
    <FilterPanel
      query={query}
      onChange={onChange}
      categories={[passives, resistors]}
      attributes={query.category !== null ? [resistance] : undefined}
      facets={facets}
      facetsLoading={false}
      refusals={{}}
    />,
  );
  return onChange;
}

/** A stateful host, so text and pin accumulate keystrokes the way the page's draft does. */
function Host({ initial, onChange }: { initial: PartQuery; onChange: (q: PartQuery) => void }) {
  const [query, setQuery] = useState(initial);
  return (
    <FilterPanel
      query={query}
      onChange={(next) => {
        setQuery(next);
        onChange(next);
      }}
      categories={[passives, resistors]}
      attributes={query.category !== null ? [resistance] : undefined}
      facets={facets}
      facetsLoading={false}
      refusals={{}}
    />
  );
}

describe("FilterPanel", () => {
  it("reports the text as it is typed", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Host initial={emptyQuery} onChange={onChange} />);

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name or number" }), "res");

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ text: "res" }));
  });

  it("lists the categories as a tree and reports the chosen one", async () => {
    const onChange = renderPanel(emptyQuery);

    const picker = screen.getByRole("combobox", { name: "Category" });
    await userEvent
      .setup()
      .selectOptions(picker, screen.getByRole("option", { name: /Resistors/ }));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ category: resistors.id, filters: [], exact: false }),
    );
  });

  it("offers 'only this category' once a category is chosen", async () => {
    const onChange = renderPanel({ ...emptyQuery, category: resistors.id });

    const only = screen.getByRole("checkbox", {
      name: "Only this category, not its subcategories",
    });
    await userEvent.setup().click(only);

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ exact: true }));
  });

  it("hides 'only this category' until a category is chosen", () => {
    renderPanel(emptyQuery);

    expect(
      screen.queryByRole("checkbox", { name: "Only this category, not its subcategories" }),
    ).not.toBeInTheDocument();
  });

  it("shows one filter per attribute of the chosen category's schema", () => {
    renderPanel({ ...emptyQuery, category: resistors.id });

    expect(screen.getByRole("textbox", { name: "Resistance at least" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Resistance at most" })).toBeInTheDocument();
  });

  it("shows no attribute filters before a category is chosen", () => {
    renderPanel(emptyQuery);

    expect(screen.queryByRole("textbox", { name: "Resistance at least" })).not.toBeInTheDocument();
  });

  it("reports the pin as it is typed", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Host initial={emptyQuery} onChange={onChange} />);

    await userEvent.setup().type(screen.getByRole("textbox", { name: "Has a pin" }), "SDA");

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ pin: "SDA" }));
  });

  it("folds behind a toggle on a phone", async () => {
    renderPanel(emptyQuery);

    // The toggle is present for the narrow layout; opening it reveals the controls.
    const toggle = screen.getByRole("button", { name: "Show filters" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await userEvent.setup().click(toggle);

    expect(screen.getByRole("button", { name: "Hide filters" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

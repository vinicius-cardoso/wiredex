import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import { aPart, refuseSearch, respondWithPartSuggestions } from "../../test/server";
import { PartPicker, type PickedPart } from "./PartPicker";

const fourK7 = aPart();
const tenK = aPart({
  id: "0199cccc-0000-7000-8000-0000000000b1",
  name: "10 kΩ 1% 0805",
  mpn: "RC0805FR-0710KL",
});
const sensor = aPart({
  id: "0199cccc-0000-7000-8000-0000000000d2",
  name: "BME280",
  manufacturer: "Bosch",
  mpn: "BME280",
  package: "LGA-8",
});

/** The picker in a form whose submit is recorded, as the BOM's add row submits on Enter. */
function Harness({ initial = null }: { initial?: PickedPart | null }) {
  const [picked, setPicked] = useState<PickedPart | null>(initial);
  const [submitted, setSubmitted] = useState(0);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted((count) => count + 1);
      }}
    >
      <PartPicker label="Part" value={picked} onChange={setPicked} />
      <p>Picked: {picked?.name ?? "none"}</p>
      <p>Submitted: {submitted}</p>
    </form>
  );
}

function renderPicker(initial: PickedPart | null = null) {
  const sent = respondWithPartSuggestions([fourK7, tenK, sensor]);
  renderWithProviders(<Harness initial={initial} />);
  return { sent, user: userEvent.setup(), box: screen.getByRole("combobox", { name: "Part" }) };
}

describe("PartPicker", () => {
  it("suggests parts by name, part number or manufacturer once typing pauses", async () => {
    const { sent, user, box } = renderPicker();

    await user.type(box, "bosch");

    const list = await screen.findByRole("listbox", { name: "Part" });
    expect(
      within(list)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["BME280 BME280 · Bosch"]);
    expect(box).toHaveAttribute("aria-expanded", "true");
    // One search for the whole word, not one per key, and at most eight parts.
    expect(sent.map((body) => [body.text, body.page, body.page_size])).toEqual([["bosch", 1, 8]]);
  });

  it("moves with the arrow keys and picks with Enter, which doesn't submit yet", async () => {
    const { user, box } = renderPicker();

    await user.type(box, "0805");
    // Offered by name: the 10k, then the 4k7.
    const first = await screen.findByRole("option", { name: /10 kΩ/ });
    await user.keyboard("{ArrowDown}");
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(box).toHaveAttribute("aria-activedescendant", first.id);
    // Down past the last wraps to the first; up from there wraps to the last.
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}");
    const second = screen.getByRole("option", { name: /4.7 kΩ/ });
    expect(box).toHaveAttribute("aria-activedescendant", second.id);

    await user.keyboard("{Enter}");

    expect(box).toHaveValue("4.7 kΩ 1% 0805");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Picked: 4.7 kΩ 1% 0805")).toBeInTheDocument();
    expect(screen.getByText("Submitted: 0")).toBeInTheDocument();

    // With the list shut, Enter reaches the form.
    await user.keyboard("{Enter}");
    expect(screen.getByText("Submitted: 1")).toBeInTheDocument();
  });

  it("shuts the list with Escape and goes back to the part picked", async () => {
    const { user, box } = renderPicker({ id: sensor.id, name: sensor.name });
    expect(box).toHaveValue("BME280");

    await user.clear(box);
    await user.type(box, "10k");
    await screen.findByRole("option", { name: /10 kΩ/ });
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    // Emptying the box let the part go; the draft that was never picked is dropped.
    expect(box).toHaveValue("");
    expect(screen.getByText("Picked: none")).toBeInTheDocument();
  });

  it("says when nothing matches, and when the search fails", async () => {
    const { user, box } = renderPicker();

    await user.type(box, "zzz");
    expect(await screen.findByText("No part matches that.")).toBeInTheDocument();

    refuseSearch("nope", 500);
    await user.type(box, "q");
    expect(await screen.findByText("The parts couldn't be searched.")).toBeInTheDocument();
  });

  it("opens on the picked part's name with an arrow key", async () => {
    const { user, box } = renderPicker({ id: fourK7.id, name: fourK7.name });

    await user.click(box);
    await user.keyboard("{ArrowDown}");

    expect(await screen.findByRole("option", { name: /4.7 kΩ/ })).toBeInTheDocument();
  });
});

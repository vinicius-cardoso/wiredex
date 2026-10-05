import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import { aUnit, respondWithUnitSearch, server } from "../../test/server";
import { type PickedUnit, UnitPicker } from "./UnitPicker";

const esp32 = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c1",
  code: "WX-U-0001",
  mac: "aa:bb:cc:00:11:22",
  status: "reserved",
});
const pico = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c2",
  code: "WX-U-0002",
  serial: "PICO-7",
  mac: "aa:bb:cc:00:11:33",
});
const broken = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c3",
  code: "WX-U-0003",
  status: "retired",
});

/** The picker in a form whose submit is recorded, as a dialog submits on Enter. */
function Harness() {
  const [picked, setPicked] = useState<PickedUnit | null>(null);
  const [submitted, setSubmitted] = useState(0);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted((count) => count + 1);
      }}
    >
      <UnitPicker label="Board" value={picked} onChange={setPicked} />
      <p>Picked: {picked?.code ?? "none"}</p>
      <p>Submitted: {submitted}</p>
    </form>
  );
}

function renderPicker() {
  const asked = respondWithUnitSearch([esp32, pico, broken]);
  renderWithProviders(<Harness />);
  return { asked, user: userEvent.setup(), box: screen.getByRole("combobox", { name: "Board" }) };
}

describe("UnitPicker", () => {
  it("finds a unit by its code once typing pauses, and picks it with Enter", async () => {
    const { asked, user, box } = renderPicker();

    await user.type(box, "0002");

    const list = await screen.findByRole("listbox", { name: "Board" });
    const option = within(list).getByRole("option");
    expect(option).toHaveTextContent("WX-U-0002 In stock · PICO-7 · aa:bb:cc:00:11:33");
    // One search for the whole code, not one per key.
    expect(asked).toEqual(["0002"]);

    await user.keyboard("{ArrowDown}");
    expect(box).toHaveAttribute("aria-activedescendant", option.id);
    await user.keyboard("{Enter}");

    expect(box).toHaveValue("WX-U-0002");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Picked: WX-U-0002")).toBeInTheDocument();
    expect(screen.getByText("Submitted: 0")).toBeInTheDocument();
  });

  it("finds units by their MAC, and announces how many match", async () => {
    const { user, box } = renderPicker();

    await user.type(box, "AA:BB:CC:00:11");

    const list = await screen.findByRole("listbox", { name: "Board" });
    expect(
      within(list)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "WX-U-0001 Reserved · aa:bb:cc:00:11:22",
      "WX-U-0002 In stock · PICO-7 · aa:bb:cc:00:11:33",
    ]);
    expect(screen.getByRole("status")).toHaveTextContent("Matching units: 2");

    await user.click(within(list).getByRole("option", { name: /WX-U-0001/ }));
    expect(screen.getByText("Picked: WX-U-0001")).toBeInTheDocument();
  });

  it("lists a retired unit as unavailable, which neither Enter nor a click picks", async () => {
    const { user, box } = renderPicker();

    await user.type(box, "WX-U-0003");

    const retired = await screen.findByRole("option", { name: /WX-U-0003/ });
    expect(retired).toHaveAttribute("aria-disabled", "true");
    expect(retired).toHaveTextContent("Retired, so it can't be picked");

    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(retired);

    expect(screen.getByText("Picked: none")).toBeInTheDocument();
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Submitted: 0")).toBeInTheDocument();
  });

  it("says when nothing matches, and shuts with Escape", async () => {
    const { user, box } = renderPicker();

    await user.type(box, "zzz");
    expect(await screen.findByText("No unit matches that.")).toBeInTheDocument();

    await user.clear(box);
    await user.type(box, "WX");
    expect(await screen.findAllByRole("option")).toHaveLength(3);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("offers the first fifty matches, the newest first", async () => {
    const many = Array.from({ length: 60 }, (_, index) =>
      aUnit({
        id: `0199dddd-0000-7000-8000-${String(index).padStart(12, "0")}`,
        code: `WX-U-${String(60 - index).padStart(4, "0")}`,
      }),
    );
    respondWithUnitSearch(many);
    const sent: string[] = [];
    // Listens only: a handler that returns nothing passes the request on to the fake above.
    server.use(
      http.get("*/api/inventory/units", ({ request }) => {
        sent.push(new URL(request.url).search);
      }),
    );
    renderWithProviders(<Harness />);
    const user = userEvent.setup();

    await user.type(screen.getByRole("combobox", { name: "Board" }), "WX-U");

    const list = await screen.findByRole("listbox", { name: "Board" });
    const options = within(list).getAllByRole("option");
    expect(options).toHaveLength(50);
    expect(options[0]).toHaveTextContent("WX-U-0060");
    expect(screen.getByRole("status")).toHaveTextContent("Matching units: 50");
    expect(sent).toEqual(["?search=WX-U&page_size=50"]);
  });
});

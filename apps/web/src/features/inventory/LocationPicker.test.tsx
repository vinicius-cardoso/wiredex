import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type FormEvent, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { aLocation, respondWithLocations } from "../../test/server";
import { LocationPicker } from "./LocationPicker";

const lab = aLocation({ name: "Lab", code: "WX-L-0001", child_count: 1 });
const cabinet = aLocation({
  id: "0199ffff-0000-7000-8000-000000000002",
  parent_id: lab.id,
  name: "Cabinet A",
  code: "WX-L-0002",
  child_count: 1,
});
const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  parent_id: cabinet.id,
  name: "Drawer 3",
  code: "WX-L-0003",
});
// Two codes where one holds the other, so typing the shorter one matches both.
const shelf = aLocation({
  id: "0199ffff-0000-7000-8000-000000000004",
  name: "Shelf",
  code: "WX-L-1000",
});
const tray = aLocation({
  id: "0199ffff-0000-7000-8000-000000000005",
  name: "Tray",
  code: "WX-L-10001",
});

type HarnessProps = {
  initial: string | null;
  problem: string | undefined;
  onPick: (locationId: string | null) => void;
  onSubmit: () => void;
};

/** The picker inside a form, holding its value the way a dialog would. */
function Harness({ initial, problem, onPick, onSubmit }: HarnessProps) {
  const [value, setValue] = useState(initial);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }
  return (
    <form onSubmit={submit}>
      <LocationPicker
        label="Location"
        value={value}
        onChange={(locationId) => {
          setValue(locationId);
          onPick(locationId);
        }}
        {...(problem ? { describedBy: "location-problem", invalid: true } : {})}
      />
      {problem && <p id="location-problem">{problem}</p>}
    </form>
  );
}

function renderPicker({
  initial = null,
  problem,
}: {
  initial?: string | null;
  problem?: string;
} = {}) {
  respondWithLocations([lab, cabinet, drawer, shelf, tray]);
  const picks: (string | null)[] = [];
  const onSubmit = vi.fn();
  renderWithProviders(
    <Harness
      initial={initial}
      problem={problem}
      onPick={(id) => picks.push(id)}
      onSubmit={onSubmit}
    />,
  );
  return { picks, onSubmit, combobox: screen.getByRole("combobox", { name: "Location" }) };
}

function optionNames() {
  const list = screen.getByRole("listbox", { name: "Location" });
  return within(list)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

describe("LocationPicker", () => {
  it("suggests locations by name, each with its path and code", async () => {
    const { combobox } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "drawer");

    const option = await screen.findByRole("option", {
      name: "Lab / Cabinet A / Drawer 3 WX-L-0003",
    });
    expect(option).toBeInTheDocument();
    expect(optionNames()).toHaveLength(1);
    expect(combobox).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Matching locations: 1");
  });

  it("suggests a location by part of its short code, in any case", async () => {
    const { combobox } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "l-0002");

    expect(await screen.findByRole("option", { name: /Cabinet A/ })).toBeInTheDocument();
    expect(optionNames()).toEqual(["Lab / Cabinet A WX-L-0002"]);
  });

  it("suggests locations by a fragment of their path, spacing around the / ignored", async () => {
    const { combobox } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "cabinet a/dra");

    expect(await screen.findByRole("option", { name: /Drawer 3/ })).toBeInTheDocument();
    expect(optionNames()).toEqual(["Lab / Cabinet A / Drawer 3 WX-L-0003"]);
  });

  it("says when nothing matches, with no list open", async () => {
    const { combobox } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "nowhere");

    expect(await screen.findByText("No location matches that.")).toBeInTheDocument();
    expect(combobox).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("is operated with the keyboard alone: arrows move, Enter picks, Escape shuts", async () => {
    const { combobox, picks } = renderPicker();
    const user = userEvent.setup();

    await user.tab();
    expect(combobox).toHaveFocus();
    // "lab" is in the name of Lab and in the path of everything inside it.
    await user.keyboard("lab");
    await screen.findByRole("option", { name: /Drawer 3/ });
    expect(optionNames()).toHaveLength(3);

    await user.keyboard("{ArrowDown}{ArrowDown}");
    const second = screen.getByRole("option", { name: /^Lab \/ Cabinet A WX/ });
    expect(combobox).toHaveAttribute("aria-activedescendant", second.id);
    expect(second).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowUp}{ArrowUp}");
    const last = screen.getByRole("option", { name: /Drawer 3/ });
    expect(combobox).toHaveAttribute("aria-activedescendant", last.id);

    await user.keyboard("{Enter}");
    expect(picks).toEqual([drawer.id]);
    expect(combobox).toHaveValue("Lab / Cabinet A / Drawer 3");
    expect(combobox).toHaveAttribute("aria-expanded", "false");
    expect(combobox).not.toHaveAttribute("aria-activedescendant");

    // A draft that isn't picked is dropped by Escape, and the pick stands.
    await user.keyboard("x{Escape}");
    expect(combobox).toHaveValue("Lab / Cabinet A / Drawer 3");
    expect(picks).toEqual([drawer.id]);

    // Down on a shut list opens it on the text as it stands, at its first match.
    await user.keyboard("{ArrowDown}");
    const picked = screen.getByRole("option", { name: /Drawer 3/ });
    expect(combobox).toHaveAttribute("aria-activedescendant", picked.id);
  });

  it("picks the location whose code is exactly the text on Enter", async () => {
    const { combobox, picks } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "wx-l-1000");
    await screen.findByRole("option", { name: /Tray/ });
    expect(optionNames()).toHaveLength(2);

    await user.keyboard("{Enter}");

    expect(picks).toEqual([shelf.id]);
    expect(combobox).toHaveValue("Shelf");
  });

  it("picks an option with a click", async () => {
    const { combobox, picks } = renderPicker();
    const user = userEvent.setup();

    await user.type(combobox, "tray");
    await user.click(await screen.findByRole("option", { name: /Tray/ }));

    expect(picks).toEqual([tray.id]);
    expect(combobox).toHaveValue("Tray");
    expect(combobox).toHaveFocus();
  });

  it("shows the picked location, and lets it go when the box is emptied", async () => {
    const { combobox, picks } = renderPicker({ initial: cabinet.id });
    const user = userEvent.setup();

    expect(await screen.findByDisplayValue("Lab / Cabinet A")).toBe(combobox);
    await user.clear(combobox);

    expect(picks).toEqual([null]);
    await user.tab();
    expect(combobox).toHaveValue("");
  });

  it("drops an unpicked draft when focus leaves", async () => {
    const { combobox, picks } = renderPicker({ initial: shelf.id });
    const user = userEvent.setup();
    await screen.findByDisplayValue("Shelf");

    await user.type(combobox, " and more");
    await user.tab();

    expect(combobox).toHaveValue("Shelf");
    expect(picks).toEqual([]);
  });

  it("lets Enter submit the form and Escape leave only once the list is shut", async () => {
    const { combobox, onSubmit } = renderPicker();
    const user = userEvent.setup();
    const heard: string[] = [];
    const listen = (event: KeyboardEvent) => heard.push(event.key);
    document.addEventListener("keydown", listen);

    try {
      await user.type(combobox, "shelf");
      await screen.findByRole("option", { name: /Shelf/ });
      // Open and nothing moved to: Enter neither picks nor submits.
      await user.keyboard("{Enter}");
      expect(onSubmit).not.toHaveBeenCalled();

      // The first Escape shuts the list and stops there; the second reaches the page.
      await user.keyboard("{Escape}");
      expect(heard).not.toContain("Escape");
      await user.keyboard("{Escape}");
      expect(heard).toContain("Escape");

      await user.keyboard("{Enter}");
      expect(onSubmit).toHaveBeenCalledOnce();
    } finally {
      document.removeEventListener("keydown", listen);
    }
  });

  it("carries the problem it is described by", () => {
    const { combobox } = renderPicker({ problem: "Pick where it goes." });

    expect(combobox).toHaveAccessibleDescription("Pick where it goes.");
    expect(combobox).toBeInvalid();
  });
});

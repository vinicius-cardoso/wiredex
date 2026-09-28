import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { createAppRouter } from "../../../app/router";
import { createTestQueryClient, renderInRouter, renderWithProviders } from "../../../test/render";
import {
  aCategory,
  aLocation,
  aPartDetails,
  respondAsLoggedIn,
  respondAsLoggedOut,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithLocations,
} from "../../../test/server";
import { type QuickAddOptions, QuickAddProvider, useQuickAdd } from "./QuickAddProvider";

const resistors = aCategory({ name: "Resistors" });
const lab = aLocation({ name: "Lab", code: "WX-L-0001", child_count: 1 });
const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  parent_id: lab.id,
  name: "Drawer 3",
  code: "WX-L-0003",
});

function respondWithTheBench() {
  respondWithCategories([resistors]);
  respondWithCategorySchema(resistors, []);
  respondWithLocations([lab, drawer]);
}

/** A page of the app, as far as quick-add cares: somewhere to type, and a way to ask for it. */
function Page({ options }: { options?: QuickAddOptions }) {
  const quickAdd = useQuickAdd();
  const [dialog, setDialog] = useState(false);
  return (
    <>
      <button type="button" onClick={() => quickAdd.open(options)}>
        Open with options
      </button>
      <label>
        Notes <input type="text" />
      </label>
      <div contentEditable suppressContentEditableWarning>
        Editable
      </div>
      <button type="button" onClick={() => setDialog(true)}>
        Open another dialog
      </button>
      {dialog && (
        <div role="dialog" aria-label="Another dialog">
          <button type="button">Inside it</button>
        </div>
      )}
    </>
  );
}

function renderPage(options?: QuickAddOptions, enabled = true) {
  respondWithTheBench();
  renderInRouter(
    <QuickAddProvider enabled={enabled}>
      <Page {...(options ? { options } : {})} />
    </QuickAddProvider>,
  );
}

function renderApp(path = "/") {
  respondWithApiVersion("0.0.0");
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

const quickAddDialog = () => screen.queryByRole("dialog", { name: "Quick add" });

describe("QuickAddProvider", () => {
  it("opens quick-add on Alt+N from anywhere but a text field", async () => {
    renderPage();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Open with options" });

    await user.keyboard("{Alt>}n{/Alt}");

    expect(await screen.findByRole("dialog", { name: "Quick add" })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Category" })).toHaveFocus();
  });

  it("leaves Alt+N to the text field that has focus", async () => {
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("textbox", { name: "Notes" }));
    await user.keyboard("{Alt>}n{/Alt}");
    expect(quickAddDialog()).toBeNull();

    // jsdom can't focus editable content, so the chord is sent from inside it instead.
    fireEvent.keyDown(screen.getByText("Editable"), { key: "n", code: "KeyN", altKey: true });
    expect(quickAddDialog()).toBeNull();
  });

  it("ignores Alt+N while another dialog is open, and other chords", async () => {
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open another dialog" }));
    await user.keyboard("{Alt>}n{/Alt}");
    expect(quickAddDialog()).toBeNull();

    // Ctrl+N is the browser's, and Alt+Shift+N is another chord.
    fireEvent.keyDown(document.body, { key: "n", code: "KeyN", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "N", code: "KeyN", altKey: true, shiftKey: true });
    expect(quickAddDialog()).toBeNull();
  });

  it("matches Option+N by its position where it is a dead key", async () => {
    renderPage();
    await screen.findByRole("button", { name: "Open with options" });

    fireEvent.keyDown(document.body, { key: "Dead", code: "KeyN", altKey: true });

    expect(await screen.findByRole("dialog", { name: "Quick add" })).toBeInTheDocument();
  });

  it("does nothing while it is turned off", async () => {
    renderPage({}, false);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open with options" }));
    await user.keyboard("{Alt>}n{/Alt}");

    expect(quickAddDialog()).toBeNull();
  });

  it("opens prefilled with a category, a location and a name, and focuses the first empty field", async () => {
    renderPage({ categoryId: resistors.id, locationId: drawer.id, name: "4.7 kΩ 1% 0805" });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open with options" }));

    const dialog = await screen.findByRole("dialog", { name: "Quick add" });
    expect(within(dialog).getByRole("combobox", { name: "Category" })).toHaveValue(resistors.id);
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("4.7 kΩ 1% 0805");
    expect(await within(dialog).findByDisplayValue("Lab / Drawer 3")).toBe(
      within(dialog).getByRole("combobox", { name: "Location" }),
    );
    expect(within(dialog).getByRole("textbox", { name: "Part number" })).toHaveFocus();
  });

  it("starts a duplicate from the part's category, name, manufacturer and package", async () => {
    const source = aPartDetails({ category_id: resistors.id, name: "10 kΩ 1% 0805" });
    renderPage({ duplicateOf: source });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Open with options" }));

    const dialog = await screen.findByRole("dialog", { name: "Duplicate 10 kΩ 1% 0805" });
    expect(within(dialog).getByRole("combobox", { name: "Category" })).toHaveValue(resistors.id);
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("10 kΩ 1% 0805");
    expect(within(dialog).getByRole("textbox", { name: "Manufacturer" })).toHaveValue("Yageo");
    expect(within(dialog).getByRole("textbox", { name: "Package" })).toHaveValue("0805");
    expect(within(dialog).getByRole("textbox", { name: "Part number" })).toHaveValue("");
  });

  it("closes with Escape and gives focus back to what opened it", async () => {
    renderPage();
    const user = userEvent.setup();
    const opener = await screen.findByRole("button", { name: "Open with options" });

    await user.click(opener);
    await screen.findByRole("combobox", { name: "Category" });
    await user.keyboard("{Escape}");

    expect(quickAddDialog()).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("needs a provider above it", () => {
    function Lonely() {
      useQuickAdd();
      return null;
    }
    // React reports the error it rethrows; the throw is what is being checked.
    const reported = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      expect(() => render(<Lonely />)).toThrow(/QuickAddProvider/);
    } finally {
      reported.mockRestore();
    }
  });
});

describe("the header's Quick add button", () => {
  it("is on every signed-in page, with its shortcut, and opens quick-add", async () => {
    respondAsLoggedIn();
    respondWithTheBench();
    renderApp();
    const user = userEvent.setup();

    const button = await screen.findByRole("button", { name: "Quick add" });
    expect(button).toHaveAttribute("aria-keyshortcuts", "Alt+N");
    expect(button).toHaveTextContent("Alt N");

    await user.click(button);
    expect(await screen.findByRole("dialog", { name: "Quick add" })).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(quickAddDialog()).toBeNull();
    expect(button).toHaveFocus();
  });

  it("isn't offered to a visitor who hasn't logged in", async () => {
    respondAsLoggedOut();
    renderApp();
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    await user.keyboard("{Alt>}n{/Alt}");

    expect(screen.queryByRole("button", { name: "Quick add" })).toBeNull();
    expect(quickAddDialog()).toBeNull();
  });
});

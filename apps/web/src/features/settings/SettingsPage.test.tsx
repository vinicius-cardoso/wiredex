import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptPreferences,
  respondAsLoggedIn,
  respondWithApiVersion,
  server,
  somePreferences,
} from "../../test/server";

function renderSettings() {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/settings"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

describe("SettingsPage", () => {
  it("compares minimums against free stock until told otherwise, and says what each means", async () => {
    acceptPreferences();
    renderSettings();

    const free = await screen.findByRole("radio", { name: /^Free stock/ });
    expect(free).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Total stock/ })).not.toBeChecked();
    expect(
      screen.getByRole("group", { name: "Compare a part's minimum stock against" }),
    ).toHaveAccessibleDescription(/when a part shows on the reorder list/);
    expect(screen.getByText(/on hand and not reserved for a build/)).toBeInTheDocument();
    expect(screen.getByText(/Everything on hand, reserved or not/)).toBeInTheDocument();
  });

  it("saves a choice as it is picked, and says so", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("radio", { name: /^Total stock/ }));

    expect(await screen.findByText("Saved.")).toHaveRole("status");
    expect(sent).toEqual([somePreferences({ stock_basis: "total" })]);
    expect(screen.getByRole("radio", { name: /^Total stock/ })).toBeChecked();
  });

  it("keeps the saved choice and says so when the save fails", async () => {
    acceptPreferences();
    server.use(http.put("*/api/preferences", () => HttpResponse.json({}, { status: 500 })));
    renderSettings();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("radio", { name: /^Total stock/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The setting couldn't be saved.");
    expect(screen.getByRole("radio", { name: /^Free stock/ })).toBeChecked();
  });

  it("is reached from the account menu", async () => {
    acceptPreferences();
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    const queryClient = createTestQueryClient();
    const history = createMemoryHistory({ initialEntries: ["/sessions"] });
    renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
      queryClient,
    });
    server.use(http.get("*/api/auth/sessions", () => HttpResponse.json([])));
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Account of / }));
    await user.click(screen.getByRole("menuitem", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Settings", level: 1 })).toBeInTheDocument();
  });

  it("saves a default minimum typed, and refuses one that isn't a number", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    const field = await screen.findByRole("textbox", { name: "Default minimum stock" });
    await user.type(field, "abc");
    expect(field).toHaveAccessibleDescription(/A whole number from 0 to 1,000,000/);
    await user.tab();
    expect(sent).toEqual([]);

    await user.clear(field);
    await user.type(field, "5{Enter}");
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.default_minimum_stock).toBe(5);
  });

  it("saves a code prefix in upper case, shows the codes it makes, and refuses a bad one", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    const field = await screen.findByRole("textbox", { name: "Code prefix" });
    expect(field).toHaveAccessibleDescription(/WX-L-0007.*WX-U-0042/);
    await user.clear(field);
    await user.type(field, "2ab");
    expect(field).toHaveAccessibleDescription(/A letter followed by up to five letters or digits/);
    await user.tab();
    expect(sent).toEqual([]);

    await user.clear(field);
    await user.type(field, "lab{Enter}");
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.code_prefix).toBe("LAB");
    expect(await screen.findByRole("textbox", { name: "Code prefix" })).toHaveAccessibleDescription(
      /LAB-L-0007/,
    );
    expect(screen.getByText(/Codes already given keep their prefix/)).toBeInTheDocument();
  });

  it("shows each date and number format with an example, and saves the one picked", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    const iso = await screen.findByRole("radio", { name: /^Year first \(ISO\)/ });
    expect(iso).toHaveAccessibleName(/2026-10-11 14:30/);
    expect(screen.getByRole("radio", { name: /^Day, month, year/ })).toHaveAccessibleName(
      /11\/10\/2026 14:30/,
    );
    expect(screen.getByRole("radio", { name: /^Comma for decimals/ })).toHaveAccessibleName(
      /1\.234,5/,
    );
    expect(screen.getByRole("radio", { name: /^Point for decimals/ })).toHaveAccessibleName(
      /1,234\.5/,
    );

    await user.click(iso);
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.date_format).toBe("iso");
  });

  it("keeps the trash for ever until a number of days is picked, and says what that does", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    const retention = await screen.findByRole("combobox", {
      name: "Keep what is moved to the trash for",
    });
    expect(retention).toHaveAccessibleDescription("Nothing is deleted from the trash on its own.");

    await user.selectOptions(retention, "30 days");
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.trash_retention_days).toBe(30);
    expect(retention).toHaveAccessibleDescription(/longer than 30 days is deleted for good/);
  });

  it("keeps every change when several are made before the first is saved", async () => {
    const sent = acceptPreferences();
    renderSettings();
    const user = userEvent.setup();

    const prefix = await screen.findByRole("textbox", { name: "Code prefix" });
    await user.clear(prefix);
    await user.type(prefix, "lab{Enter}");
    await user.click(screen.getByRole("radio", { name: /^Year first/ }));

    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1]).toMatchObject({ code_prefix: "LAB", date_format: "iso" });
  });
});

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
    expect(sent).toEqual([{ stock_basis: "total" }]);
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
});

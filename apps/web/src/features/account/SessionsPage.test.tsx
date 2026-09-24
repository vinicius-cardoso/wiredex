import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aSession,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithSessions,
  server,
} from "../../test/server";

const phone = aSession({
  id: "0199aaaa-0000-7000-8000-0000000000b2",
  device: "Wiredex-Mobile/1.0",
  current: false,
});

function renderSessionsPage() {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/sessions"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

describe("SessionsPage", () => {
  it("lists every device, naming the browsers it knows and marking this one", async () => {
    respondWithSessions([aSession(), phone]);
    renderSessionsPage();

    const rows = await screen.findAllByRole("listitem");

    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Firefox on Linux");
    expect(rows[0]).toHaveTextContent("This device");
    expect(rows[1]).toHaveTextContent("Wiredex-Mobile/1.0");
    expect(rows[1]).not.toHaveTextContent("This device");
  });

  it("logs another device out and drops it from the list", async () => {
    respondWithSessions([aSession(), phone]);
    renderSessionsPage();

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Log out Wiredex-Mobile/1.0" }));

    await expect.poll(() => screen.queryAllByRole("listitem").length).toBe(1);
    expect(screen.queryByText("Wiredex-Mobile/1.0")).not.toBeInTheDocument();
  });

  it("returns to the login page after logging this device out", async () => {
    respondWithSessions([aSession()]);
    renderSessionsPage();

    const row = (await screen.findAllByRole("listitem"))[0] as HTMLElement;
    await userEvent.setup().click(within(row).getByRole("button"));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("says so when the devices can't be loaded", async () => {
    renderSessionsPage();
    server.use(http.get("*/api/auth/sessions", () => HttpResponse.error()));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});

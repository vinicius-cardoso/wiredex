import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderWithProviders } from "../test/render";
import {
  acceptLogins,
  acceptLogout,
  OWNER,
  respondAsLoggedIn,
  respondAsLoggedOut,
  respondWithActivity,
  respondWithApiVersion,
  respondWithBoardList,
  respondWithFirmwareList,
  respondWithProjects,
  respondWithProjectTags,
  respondWithSessions,
  respondWithShortRevisions,
  respondWithTiedUpParts,
  respondWithTrash,
  server,
} from "../test/server";
import { createAppRouter } from "./router";

function renderAt(path: string) {
  respondWithApiVersion("0.0.0");
  // The dashboard's three reads, answered empty for every test that lands on it.
  respondWithTiedUpParts([]);
  respondWithShortRevisions([]);
  respondWithActivity([]);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return router;
}

async function logIn(password = "correct horse battery") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "owner@example.com");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Log in" }));
}

describe("app routes", () => {
  it("opens the dashboard inside the app layout", async () => {
    respondAsLoggedIn();
    renderAt("/");

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Wiredex v");
  });

  it("shows a not-found page for unknown paths", async () => {
    respondAsLoggedIn();
    renderAt("/no/such/page");

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the dashboard" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("opens the boards list from the Boards nav entry", async () => {
    respondAsLoggedIn();
    respondWithBoardList([]);
    renderAt("/units");

    expect(await screen.findByRole("heading", { name: "Boards", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Boards" })).toHaveAttribute("href", "/units");
  });

  it("offers Projects in the navigation, after Boards", async () => {
    respondAsLoggedIn();
    respondWithProjects([]);
    respondWithProjectTags([]);
    renderAt("/projects");
    expect(await screen.findByRole("heading", { name: "Projects", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links.indexOf("Projects")).toBe(links.indexOf("Boards") + 1);
    expect(within(nav).getByRole("link", { name: "Projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
  });

  it("offers Firmware in the navigation, after Projects", async () => {
    respondAsLoggedIn();
    respondWithFirmwareList([]);
    renderAt("/firmware");

    expect(await screen.findByRole("heading", { name: "Firmware", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links.indexOf("Firmware")).toBe(links.indexOf("Projects") + 1);
    expect(within(nav).getByRole("link", { name: "Firmware" })).toHaveAttribute(
      "href",
      "/firmware",
    );
  });

  it("offers the Trash last in the navigation", async () => {
    // 16-soft-delete-and-trash, requirement 9.2.
    respondAsLoggedIn();
    respondWithTrash([]);
    renderAt("/trash");

    expect(await screen.findByRole("heading", { name: "Trash", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links.at(-1)).toBe("Trash");
    expect(within(nav).getByRole("link", { name: "Trash" })).toHaveAttribute("href", "/trash");
  });

  it("offers Activity in the navigation, just before the Trash", async () => {
    // 17-history, requirement 7.1.
    respondAsLoggedIn();
    respondWithActivity([]);
    renderAt("/activity");

    expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links.slice(-2)).toEqual(["Activity", "Trash"]);
    expect(within(nav).getByRole("link", { name: "Activity" })).toHaveAttribute(
      "href",
      "/activity",
    );
  });
});

describe("logging in", () => {
  it("sends visitors to the login page, then back where they were going", async () => {
    respondAsLoggedOut();
    acceptLogins();
    const router = renderAt("/");

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(router.state.location.search).toEqual({ redirect: "/" });

    await logIn();

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("says why a login failed and stays on the page", async () => {
    respondAsLoggedOut();
    acceptLogins();
    renderAt("/login");

    await logIn("not the password");

    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
    expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("skips the login page when already logged in", async () => {
    respondAsLoggedIn();
    renderAt("/login?redirect=%2F%2Fevil.example");

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

describe("logging out", () => {
  it("shows who is logged in, and returns to the login page after logging out", async () => {
    respondAsLoggedIn();
    acceptLogout();
    renderAt("/");

    const user = userEvent.setup();

    // The initials open a menu that says who it is, in full.
    const account = await screen.findByRole("button", { name: "Account of Owner" });
    expect(account).toHaveTextContent("O");
    await user.click(account);
    const menu = screen.getByRole("menu", { name: "Your account" });
    expect(menu).toHaveTextContent("Owner");
    expect(menu).toHaveTextContent(OWNER.email);

    await user.click(within(menu).getByRole("menuitem", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your account" })).not.toBeInTheDocument();
  });

  it("keeps the account menu shut until asked, and shuts it on Escape or a click elsewhere", async () => {
    respondAsLoggedIn();
    renderAt("/");
    const user = userEvent.setup();
    const account = await screen.findByRole("button", { name: "Account of Owner" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(account);
    expect(account).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(account).toHaveFocus();

    await user.click(account);
    await user.click(screen.getByRole("navigation", { name: "Main navigation" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("reaches the devices page from the account menu, which then shuts", async () => {
    respondAsLoggedIn();
    respondWithSessions([]);
    renderAt("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Account of Owner" }));
    await user.click(screen.getByRole("menuitem", { name: "Devices" }));

    expect(await screen.findByRole("heading", { name: "Your devices" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("guests", () => {
  it("see when their access ends", async () => {
    respondAsLoggedIn({ ...OWNER, name: "Friend", expires_at: "2026-10-01T12:00:00Z" });
    renderAt("/");

    const account = await screen.findByRole("region", { name: "Your account" });
    expect(account).toHaveTextContent("Guest until Oct 1, 2026");
  });

  it("the owner sees no expiry", async () => {
    respondAsLoggedIn();
    renderAt("/");

    expect(await screen.findByRole("region", { name: "Your account" })).not.toHaveTextContent(
      "Guest until",
    );
  });
});

describe("when the API can't be reached", () => {
  it("shows an error page that can try again", async () => {
    server.use(http.get("*/api/auth/me", () => HttpResponse.error()));
    renderAt("/");

    expect(
      await screen.findByRole("heading", { name: "Something went wrong" }),
    ).toBeInTheDocument();

    respondAsLoggedIn();
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

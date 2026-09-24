import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderWithProviders } from "../test/render";
import {
  acceptLogins,
  acceptLogout,
  respondAsLoggedIn,
  respondAsLoggedOut,
  respondWithApiVersion,
} from "../test/server";
import { createAppRouter } from "./router";

function renderAt(path: string) {
  respondWithApiVersion("0.0.0");
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

    const account = await screen.findByRole("region", { name: "Your account" });
    expect(account).toHaveTextContent("Owner");

    await userEvent.setup().click(screen.getByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your account" })).not.toBeInTheDocument();
  });
});

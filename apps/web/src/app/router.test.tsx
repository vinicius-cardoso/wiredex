import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../test/render";
import { respondWithApiVersion } from "../test/server";
import { createAppRouter } from "./router";

function renderAt(path: string) {
  respondWithApiVersion("0.0.0");
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />);
}

describe("app routes", () => {
  it("opens the dashboard inside the app layout", async () => {
    renderAt("/");

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Wiredex v");
  });

  it("shows a not-found page for unknown paths", async () => {
    renderAt("/no/such/page");

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the dashboard" })).toHaveAttribute(
      "href",
      "/",
    );
  });
});

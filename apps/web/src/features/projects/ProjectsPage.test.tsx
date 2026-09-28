import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aProjectSummary,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithProjects,
  respondWithProjectTags,
} from "../../test/server";

const weatherStation = aProjectSummary({
  name: "Weather station",
  tags: ["esp32", "i2c", "outdoor"],
  revision_count: 2,
  latest_revision: {
    id: "0199eeee-0000-7000-8000-00000000000b",
    label: "B",
    summary: "perfboard",
    status: "draft",
  },
  last_activity: "2026-09-27T12:00:00Z",
});
const greenhouse = aProjectSummary({
  id: "0199eeee-0000-7000-8000-000000000002",
  name: "Greenhouse controller",
  tags: ["esp32", "relay"],
  latest_revision: {
    id: "0199eeee-0000-7000-8000-00000000002a",
    label: "A",
    summary: null,
    status: "draft",
  },
  last_activity: "2026-09-26T09:00:00Z",
});

function renderProjectsPage(initial = "/projects", projects = [weatherStation, greenhouse]) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const asked = respondWithProjects(projects);
  respondWithProjectTags([
    { tag: "esp32", projects: 2 },
    { tag: "i2c", projects: 1 },
    { tag: "outdoor", projects: 1 },
    { tag: "relay", projects: 1 },
  ]);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [initial] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router, asked };
}

function projectNames(): string[] {
  return screen.queryAllByRole("rowheader").map((cell) => cell.textContent ?? "");
}

describe("ProjectsPage", () => {
  it("lists each project with its tags, latest revision and last activity", async () => {
    renderProjectsPage();

    const link = await screen.findByRole("link", { name: "Weather station" });
    expect(link).toHaveAttribute("href", `/projects/${weatherStation.id}`);
    expect(projectNames()).toEqual(["Weather station", "Greenhouse controller"]);
    const row = link.closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("esp32");
    expect(row).toHaveTextContent("i2c");
    expect(row).toHaveTextContent("B – perfboard Draft");
    expect(within(row).getByText("Sep 27, 2026")).toHaveAttribute(
      "datetime",
      weatherStation.last_activity,
    );
    const other = screen.getByRole("link", { name: "Greenhouse controller" }).closest("tr");
    expect(other).toHaveTextContent("A Draft");
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute(
      "href",
      "/projects/new",
    );
  });

  it("writes the search to the address once typing pauses", async () => {
    const { router, asked } = renderProjectsPage();
    await screen.findByRole("link", { name: "Weather station" });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search projects by name" }), "green");

    await waitFor(() => expect(router.state.location.search).toEqual({ q: "green" }));
    await waitFor(() => expect(projectNames()).toEqual(["Greenhouse controller"]));
    expect(asked.at(-1)?.get("q")).toBe("green");
  });

  it("toggles a tag, pressed and in the address, and asks the API for it", async () => {
    const { router, asked } = renderProjectsPage();
    await screen.findByRole("link", { name: "Weather station" });
    const tags = screen.getByRole("group", { name: "Filter by tag" });
    const i2c = within(tags).getByRole("button", { name: "i2c (1)" });
    expect(i2c).toHaveAttribute("aria-pressed", "false");

    const user = userEvent.setup();
    await user.click(i2c);

    await waitFor(() => expect(router.state.location.search).toEqual({ tag: ["i2c"] }));
    expect(within(tags).getByRole("button", { name: "i2c (1)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await waitFor(() => expect(projectNames()).toEqual(["Weather station"]));
    expect(asked.at(-1)?.getAll("tag")).toEqual(["i2c"]);

    await user.click(within(tags).getByRole("button", { name: "i2c (1)" }));
    await waitFor(() => expect(router.state.location.search).toEqual({}));
  });

  it("reads the filters from the address", async () => {
    renderProjectsPage("/projects?q=weather&tag=%5B%22esp32%22%5D");

    await waitFor(() => expect(projectNames()).toEqual(["Weather station"]));
    expect(screen.getByRole("searchbox", { name: "Search projects by name" })).toHaveValue(
      "weather",
    );
    expect(screen.getByRole("button", { name: "esp32 (2)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("offers to clear the filters when nothing matches", async () => {
    const { router } = renderProjectsPage("/projects?q=nowhere");

    expect(await screen.findByText("No project matches this search.")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));

    await waitFor(() => expect(router.state.location.search).toEqual({}));
    expect(await screen.findByRole("link", { name: "Weather station" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search projects by name" })).toHaveValue("");
  });

  it("invites a first project when there is none", async () => {
    renderProjectsPage("/projects", []);

    expect(
      await screen.findByText("No projects yet. Start one for the next thing you build."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });
});

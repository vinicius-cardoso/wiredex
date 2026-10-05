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

  describe("in pages", () => {
    // Sixty projects, so a list of 50 has two pages and a list of 25 has three; every other
    // one is built, for the status filter.
    const many = Array.from({ length: 60 }, (_, index) => {
      const number = String(index + 1).padStart(2, "0");
      return aProjectSummary({
        id: `0199eeee-0000-7000-8000-0000000001${number}`,
        name: `Project ${number}`,
        latest_revision: {
          id: `0199eeee-0000-7000-8000-0000000002${number}`,
          label: "A",
          summary: null,
          status: index % 2 === 0 ? "draft" : "built",
        },
      });
    });

    function pages() {
      return screen.getByRole("navigation", { name: "Pages of the projects list" });
    }

    /** Waits for the bar to say which rows are on screen. */
    async function showing(range: string) {
      const bar = await screen.findByRole("navigation", { name: "Pages of the projects list" });
      return within(bar).findByText(range);
    }

    it("shows 50 at a time and says how many there are", async () => {
      renderProjectsPage("/projects", many);

      expect(await showing("1–50 of 60")).toBeInTheDocument();
      expect(projectNames()).toHaveLength(50);
      expect(projectNames()[0]).toBe("Project 01");
      expect(within(pages()).getByRole("button", { name: "Page 1" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    });

    it("puts the page in the address, and Back returns to the one before", async () => {
      const { router } = renderProjectsPage("/projects", many);
      await showing("1–50 of 60");

      await userEvent.setup().click(within(pages()).getByRole("button", { name: "Next page" }));

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 2 }));
      expect(projectNames()).toEqual(many.slice(50).map((project) => project.name));
      expect(within(pages()).getByText("51–60 of 60")).toBeInTheDocument();

      router.history.back();

      await waitFor(() => expect(router.state.location.search).toEqual({}));
      expect(projectNames()).toHaveLength(50);
      expect(within(pages()).getByText("1–50 of 60")).toBeInTheDocument();
    });

    it("puts a new page size in the address", async () => {
      const { router } = renderProjectsPage("/projects", many);
      await showing("1–50 of 60");

      await userEvent
        .setup()
        .selectOptions(within(pages()).getByRole("combobox", { name: "Per page" }), "25");

      await waitFor(() => expect(router.state.location.search).toEqual({ size: 25 }));
      expect(projectNames()).toHaveLength(25);
    });

    it("starts again at page 1 for a new search or status, at the size chosen", async () => {
      const { router } = renderProjectsPage("/projects?page=2&size=25", many);
      await showing("26–50 of 60");
      const user = userEvent.setup();

      await user.type(screen.getByRole("searchbox", { name: "Search projects by name" }), "Pro");

      await waitFor(() => expect(router.state.location.search).toEqual({ q: "Pro", size: 25 }));
      await user.click(within(pages()).getByRole("button", { name: "Page 2" }));
      await waitFor(() =>
        expect(router.state.location.search).toEqual({ q: "Pro", page: 2, size: 25 }),
      );

      await user.selectOptions(
        screen.getByRole("combobox", { name: "Latest revision's status" }),
        "built",
      );

      await waitFor(() =>
        expect(router.state.location.search).toEqual({ q: "Pro", status: "built", size: 25 }),
      );
      expect(within(pages()).getByText("1–25 of 30")).toBeInTheDocument();
    });

    it("keeps the size when the filters are cleared", async () => {
      const { router } = renderProjectsPage("/projects?q=Project&page=2&size=25", many);
      await showing("26–50 of 60");

      await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));

      await waitFor(() => expect(router.state.location.search).toEqual({ size: 25 }));
    });

    it("opens the last page for one past the end, and says so in the address", async () => {
      const { router } = renderProjectsPage("/projects?page=9&size=25", many);

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 3, size: 25 }));
      expect(within(pages()).getByText("51–60 of 60")).toBeInTheDocument();
      expect(projectNames()).toHaveLength(10);
      // The address was replaced, not added to, so Back doesn't return to the bad page.
      expect(router.history.length).toBe(1);
    });

    it("falls back to the first page of 50 for a page and size it can't read", async () => {
      const { router } = renderProjectsPage("/projects?page=abc&size=7", many);

      expect(await showing("1–50 of 60")).toBeInTheDocument();
      expect(projectNames()).toHaveLength(50);
      expect(within(pages()).getByRole("combobox", { name: "Per page" })).toHaveValue("50");

      await userEvent.setup().click(within(pages()).getByRole("button", { name: "Next page" }));

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 2 }));
    });
  });

  it("invites a first project when there is none", async () => {
    renderProjectsPage("/projects", []);

    expect(
      await screen.findByText("No projects yet. Start one for the next thing you build."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });
});

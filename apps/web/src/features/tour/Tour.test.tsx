import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  OWNER,
  respondAsLoggedIn,
  respondWithActivity,
  respondWithApiVersion,
  respondWithBenchCounts,
  respondWithCategories,
  respondWithProjects,
  respondWithProjectTags,
  respondWithShortRevisions,
  respondWithTiedUpParts,
} from "../../test/server";

type Options = {
  at?: string;
  /** More fakes, laid over the ones every test gets: the counts answer the same addresses. */
  fakes?: () => void;
  counts?: Parameters<typeof respondWithBenchCounts>[0];
  guest?: boolean;
  language?: "en" | "pt-BR";
};

function renderApp({ at = "/", fakes, counts = {}, guest = false, language = "en" }: Options = {}) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn(guest ? { ...OWNER, expires_at: "2099-01-01T12:00:00Z" } : OWNER);
  respondWithBenchCounts(counts);
  respondWithTiedUpParts([]);
  respondWithShortRevisions([]);
  respondWithActivity([]);
  fakes?.();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [at] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient, language });
  return { router, user: userEvent.setup() };
}

const offer = () => screen.findByRole("region", { name: "Tour" });
const card = () => screen.getByRole("dialog");
const missions = () => screen.findByRole("complementary", { name: "Getting started" });

describe("the tour", () => {
  it("is offered on the dashboard until it is answered, and never again on this device", async () => {
    const { user } = renderApp();
    await user.click(within(await offer()).getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("region", { name: "Tour" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.parse(localStorage.getItem("wiredex.tour") ?? "{}")).toMatchObject({
      offered: true,
      missions: false,
    });
  });

  it("looks around a stop at a time, by button and by keyboard", async () => {
    const { user } = renderApp();
    await user.click(within(await offer()).getByRole("button", { name: "Take the tour" }));

    expect(card()).toHaveAccessibleName("Welcome to Wiredex");
    expect(card()).toHaveAccessibleDescription(/a short list of first things to do/);
    expect(card()).toHaveTextContent("1 of 10");
    expect(within(card()).getByRole("button", { name: "Next" })).toHaveFocus();
    expect(within(card()).queryByRole("button", { name: "Back" })).toBeNull();
    // Answered by taking it, so the dashboard stops offering.
    expect(screen.queryByRole("region", { name: "Tour" })).toBeNull();

    await user.keyboard("{Enter}");
    expect(card()).toHaveAccessibleName("Parts and categories");
    expect(within(card()).getByRole("button", { name: "Next" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(card()).toHaveAccessibleName("Locations");
    await user.keyboard("{ArrowLeft}");
    await user.click(within(card()).getByRole("button", { name: "Back" }));
    expect(card()).toHaveAccessibleName("Welcome to Wiredex");

    for (let stop = 1; stop < 10; stop += 1) await user.keyboard("{ArrowRight}");
    expect(card()).toHaveAccessibleName("Your account");
    expect(card()).toHaveTextContent("10 of 10");
    expect(within(card()).queryByRole("button", { name: "Skip" })).toBeNull();
    await user.click(within(card()).getByRole("button", { name: "Finish" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await missions()).toBeVisible();
  });

  it("leaves on Escape, on Skip and on the dimmed page, the missions following", async () => {
    const { user } = renderApp();
    await user.click(within(await offer()).getByRole("button", { name: "Take the tour" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    const panel = await missions();

    // From the account menu, as often as wanted.
    await user.click(screen.getByRole("button", { name: /^Account of/ }));
    await user.click(screen.getByRole("menuitem", { name: "Take the tour" }));
    expect(panel).not.toBeInTheDocument();
    await user.click(within(card()).getByRole("button", { name: "Skip" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Account of/ }));
    await user.click(screen.getByRole("menuitem", { name: "Take the tour" }));
    await user.click(screen.getByRole("button", { name: "Leave the tour" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("ticks the missions the bench already covers, and leads to the others", async () => {
    localStorage.setItem("wiredex.tour", JSON.stringify({ offered: true, missions: true }));
    const { user, router } = renderApp({ counts: { locations: 1, parts: 3 } });

    const panel = await missions();
    expect(await within(panel).findByText("2 of 7 done")).toBeVisible();
    expect(within(panel).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    const items = within(panel).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "✓Add a place to keep things (done)",
      "Create a category for your parts (to do)Take me there",
      "✓Describe your first part (done)",
      "Start a project (to do)Take me there",
      "Keep a firmware (to do)Take me there",
      "Track a board (to do)Take me there",
      "Open the palette with Ctrl K (to do)Show me",
    ]);

    await user.click(within(items[3] as HTMLElement).getByRole("link", { name: "Take me there" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/projects/new"));
    // The list follows from page to page.
    expect(await missions()).toBeVisible();
  });

  it("points at the search button for the palette's mission, and ticks it once it is opened", async () => {
    localStorage.setItem("wiredex.tour", JSON.stringify({ offered: true, missions: true }));
    const { user } = renderApp();
    const panel = await missions();
    expect(await within(panel).findByText("0 of 7 done")).toBeVisible();

    await user.click(within(panel).getByRole("button", { name: "Show me" }));
    expect(card()).toHaveAccessibleName("Find anything");
    expect(card()).toHaveAccessibleDescription(/Opening it once ticks this off/);
    await user.click(within(card()).getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("{Escape}");
    expect(await within(await missions()).findByText("1 of 7 done")).toBeVisible();
    expect(JSON.parse(localStorage.getItem("wiredex.tour") ?? "{}").marked).toEqual(["palette"]);
  });

  it("says when every mission is done, and hides for good", async () => {
    localStorage.setItem(
      "wiredex.tour",
      JSON.stringify({ offered: true, missions: true, marked: ["palette"] }),
    );
    const { user } = renderApp({
      counts: { parts: 1, boards: 1, projects: 1, firmware: 1, locations: 1, categories: 1 },
    });
    const panel = await missions();
    expect(await within(panel).findByText("All done. The bench is yours.")).toBeVisible();
    expect(within(panel).queryByRole("link", { name: "Take me there" })).toBeNull();

    await user.click(within(panel).getByRole("button", { name: "Hide" }));
    expect(screen.queryByRole("complementary", { name: "Getting started" })).toBeNull();
    expect(JSON.parse(localStorage.getItem("wiredex.tour") ?? "{}").missions).toBe(false);
  });

  it("starts from the palette's command", async () => {
    localStorage.setItem("wiredex.tour", JSON.stringify({ offered: true }));
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Dashboard", level: 1 });
    await user.keyboard("{Control>}k{/Control}");
    await user.type(await screen.findByRole("combobox"), "tour");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Welcome to Wiredex" })).toBeVisible();
  });

  it("shows a guest around the demo bench, and gives them no missions", async () => {
    const { user } = renderApp({ guest: true });
    await user.click(within(await offer()).getByRole("button", { name: "Take the tour" }));
    expect(card()).toHaveAccessibleDescription(/demo bench with sample data, reset every night/);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Getting started" })).toBeNull();
  });

  it("speaks Brazilian Portuguese", async () => {
    const { user } = renderApp({ language: "pt-BR" });
    await user.click(
      within(await screen.findByRole("region", { name: "Tour" })).getByRole("button", {
        name: "Fazer o tour",
      }),
    );
    expect(card()).toHaveAccessibleName("Boas-vindas ao Wiredex");
    expect(card()).toHaveTextContent("1 de 10");
    await user.keyboard("{Escape}");
    expect(
      await screen.findByRole("complementary", { name: "Primeiros passos" }),
    ).toHaveTextContent("0 de 7 concluídos");
  });
});

describe("a page's own tour", () => {
  const passives = aCategory({ name: "Passives" });

  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole("button", { name: /^Account of/ }));
  }

  it("is offered from the account menu on a page that has one, and nowhere else", async () => {
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Dashboard", level: 1 });
    await openMenu(user);
    expect(screen.getByRole("menuitem", { name: "Take the tour" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: "Tour of this page" })).toBeNull();
  });

  it("points at what is on the page, a stop at a time", async () => {
    const { user } = renderApp({
      at: "/categories",
      fakes: () => respondWithCategories([passives]),
    });
    await screen.findByRole("treeitem", { name: "Passives" });
    await openMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Tour of this page" }));

    expect(card()).toHaveAccessibleName("Adding");
    expect(card()).toHaveAccessibleDescription(/^Type a name and press Add\./);
    expect(card()).toHaveTextContent("1 of 3");
    await user.keyboard("{Enter}");
    expect(card()).toHaveAccessibleName("The tree");
    expect(card()).toHaveAccessibleDescription(/passes its fields and its settings down/);
    await user.keyboard("{ArrowRight}");
    expect(card()).toHaveAccessibleName("The picked one");
    expect(card()).toHaveTextContent("3 of 3");
    await user.click(within(card()).getByRole("button", { name: "Finish" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // A page's tour is its own: it neither answers the dashboard's offer nor opens the list.
    expect(localStorage.getItem("wiredex.tour")).toBeNull();
  });

  it("leaves out what the page doesn't show, and ends when the page is left", async () => {
    const { user, router } = renderApp({
      at: "/projects",
      fakes: () => {
        respondWithProjects([]);
        respondWithProjectTags([]);
      },
    });
    await screen.findByRole("heading", { name: "Projects", level: 1 });
    await openMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Tour of this page" }));

    // No project yet, so there is neither a list nor a bar of pages to point at.
    expect(card()).toHaveAccessibleName("Adding");
    expect(card()).toHaveTextContent("1 of 2");
    await user.keyboard("{ArrowRight}");
    expect(card()).toHaveAccessibleName("Filters");
    expect(within(card()).getByRole("button", { name: "Finish" })).toBeVisible();

    await act(() => router.navigate({ to: "/" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("starts from the list of first things to do, which steps aside for it", async () => {
    localStorage.setItem("wiredex.tour", JSON.stringify({ offered: true, missions: true }));
    const { user } = renderApp({
      at: "/categories",
      fakes: () => respondWithCategories([passives]),
    });
    const panel = await missions();

    await user.click(within(panel).getByRole("button", { name: "Tour of this page" }));
    expect(card()).toHaveAccessibleName("Adding");
    expect(screen.queryByRole("complementary", { name: "Getting started" })).toBeNull();
    await user.keyboard("{Escape}");
    expect(await missions()).toBeVisible();
  });

  it("speaks Brazilian Portuguese", async () => {
    const { user } = renderApp({
      at: "/categories",
      language: "pt-BR",
      fakes: () => respondWithCategories([passives]),
    });
    await screen.findByRole("treeitem", { name: "Passives" });
    await user.click(await screen.findByRole("button", { name: /^Conta de/ }));
    await user.click(screen.getByRole("menuitem", { name: "Tour desta página" }));
    expect(card()).toHaveAccessibleName("Adicionar");
    expect(card()).toHaveTextContent("1 de 3");
  });
});

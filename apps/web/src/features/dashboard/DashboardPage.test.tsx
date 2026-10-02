import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aBomPart,
  aBomPartFacts,
  aChange,
  aPartHolding,
  aRevisionRef,
  aShortRevision,
  aTiedUpPart,
  respondAsLoggedIn,
  respondWithActivity,
  respondWithApiVersion,
  respondWithShortRevisions,
  respondWithTiedUpParts,
  server,
} from "../../test/server";

const RESISTOR = aTiedUpPart({
  reserved: 3,
  consumed: 5,
  revisions: [
    aPartHolding({
      revision: aRevisionRef({
        id: "0199eeee-0000-7000-8000-0000000000b1",
        project_id: "0199eeee-0000-7000-8000-0000000000b0",
        project_name: "Robot",
        status: "built",
      }),
      consumed: 5,
    }),
    aPartHolding({ revision: aRevisionRef({ summary: "breadboard" }), reserved: 3 }),
  ],
});
const SENSOR_ID = "0199cccc-0000-7000-8000-0000000000c2";
const SHORT = aShortRevision({ revision: aRevisionRef({ summary: "breadboard" }) }, [
  aBomPart({
    part_id: SENSOR_ID,
    part: aBomPartFacts({ name: "BME280" }),
    need: 4,
    available: 1,
    short: 3,
    status: "short",
  }),
  aBomPart({
    part_id: "0199cccc-0000-7000-8000-0000000000c3",
    part: null,
    need: 1,
    available: null,
    short: 0,
    status: "unknown_part",
  }),
]);

function renderDashboard(language: "en" | "pt-BR" = "en") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
    language,
  });
}

async function panel(name: string): Promise<HTMLElement> {
  return screen.findByRole("region", { name });
}

describe("DashboardPage", () => {
  it("shows what the builds hold, each part and revision linking to its page", async () => {
    respondWithTiedUpParts([RESISTOR]);
    respondWithShortRevisions([]);
    respondWithActivity([aChange()]);
    renderDashboard();

    const tiedUp = await panel("Tied up in builds");
    const part = await within(tiedUp).findByRole("link", { name: "4.7 kΩ 1% 0805" });
    expect(part).toHaveAttribute("href", `/parts/${RESISTOR.part_id}`);
    expect(tiedUp).toHaveTextContent("3 reserved · 5 in builds");
    const builds = within(tiedUp).getByRole("list", { name: "Builds holding 4.7 kΩ 1% 0805" });
    const [robot, station] = within(builds).getAllByRole("listitem");
    expect(within(robot as HTMLElement).getByRole("link", { name: "Robot · A" })).toHaveAttribute(
      "href",
      "/projects/0199eeee-0000-7000-8000-0000000000b0/revisions/0199eeee-0000-7000-8000-0000000000b1",
    );
    expect(robot).toHaveTextContent("5 in the build");
    expect(
      within(station as HTMLElement).getByRole("link", {
        name: "Weather station · A – breadboard",
      }),
    ).toBeVisible();
    expect(station).toHaveTextContent("3 reserved");
  });

  it("says how many more parts are tied up past the page, and names an unknown part", async () => {
    const parts = Array.from({ length: 21 }, (_, index) =>
      aTiedUpPart({ part_id: `0199cccc-0000-7000-8000-${String(index).padStart(12, "0")}` }),
    );
    parts[0] = aTiedUpPart({ part_id: "0199cccc-0000-7000-8000-0000000000ff", part: null });
    respondWithTiedUpParts(parts);
    respondWithShortRevisions([]);
    respondWithActivity([]);
    renderDashboard();

    const tiedUp = await panel("Tied up in builds");
    expect(await within(tiedUp).findByText("And 1 more part.")).toBeVisible();
    expect(within(tiedUp).getByRole("link", { name: "Unknown part" })).toHaveAttribute(
      "href",
      "/parts/0199cccc-0000-7000-8000-0000000000ff",
    );
  });

  it("shows each short draft with the parts it is missing", async () => {
    respondWithTiedUpParts([]);
    respondWithShortRevisions([SHORT]);
    respondWithActivity([]);
    renderDashboard();

    const shortages = await panel("Shortages");
    expect(
      await within(shortages).findByRole("link", { name: "Weather station · A – breadboard" }),
    ).toHaveAttribute(
      "href",
      `/projects/${SHORT.revision.project_id}/revisions/${SHORT.revision.id}`,
    );
    expect(shortages).toHaveTextContent("2 parts missing");
    const missing = within(shortages).getByRole("list", {
      name: "What Weather station A is missing",
    });
    const [sensor, unknown] = within(missing).getAllByRole("listitem");
    expect(within(sensor as HTMLElement).getByRole("link", { name: "BME280" })).toHaveAttribute(
      "href",
      `/parts/${SENSOR_ID}`,
    );
    expect(sensor).toHaveTextContent("3 short needs 4, 1 in stock");
    expect(
      within(unknown as HTMLElement).getByRole("link", { name: "Unknown part" }),
    ).toBeVisible();
    expect(unknown).toHaveTextContent("Unknown part");
  });

  it("says how many more drafts are short past the page", async () => {
    const drafts = Array.from({ length: 22 }, (_, index) =>
      aShortRevision({
        revision: aRevisionRef({
          id: `0199eeee-0000-7000-8000-${String(index).padStart(12, "0")}`,
        }),
      }),
    );
    respondWithTiedUpParts([]);
    respondWithShortRevisions(drafts);
    respondWithActivity([]);
    renderDashboard();

    const shortages = await panel("Shortages");
    expect(await within(shortages).findByText("And 2 more drafts.")).toBeVisible();
  });

  it("lists the ten newest changes and links to the whole activity", async () => {
    const asked: string[] = [];
    server.use(
      http.get("*/api/history", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("limit") ?? "");
        return HttpResponse.json({ changes: [aChange()], next_cursor: "41" });
      }),
    );
    respondWithTiedUpParts([]);
    respondWithShortRevisions([]);
    renderDashboard();

    const activity = await panel("Recent activity");
    const changes = await within(activity).findByRole("list", { name: "Recent changes" });
    const [change] = within(changes).getAllByRole("listitem");
    expect(change).toHaveTextContent("Edited");
    expect(change).toHaveTextContent("by Owner");
    expect(
      within(change as HTMLElement).getByRole("link", { name: "Part 4.7 kΩ 1% 0805" }),
    ).toHaveAttribute("href", `/parts/${aChange().record.id}`);
    expect(within(activity).getByRole("link", { name: "All activity" })).toHaveAttribute(
      "href",
      "/activity",
    );
    expect(asked).toEqual(["10"]);
    // The rows and the restore stay on the activity page.
    expect(within(activity).queryByRole("button")).toBeNull();
  });

  it("keeps the invitation while every panel is empty", async () => {
    respondWithTiedUpParts([]);
    respondWithShortRevisions([]);
    respondWithActivity([]);
    renderDashboard();

    expect(await screen.findByText(/Nothing on the bench yet\. Describe your parts/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "Tied up in builds" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  });

  it("says when one panel is empty while another has something", async () => {
    respondWithTiedUpParts([]);
    respondWithShortRevisions([]);
    respondWithActivity([aChange()]);
    renderDashboard();

    expect(
      await within(await panel("Tied up in builds")).findByText("No build holds any stock."),
    ).toBeVisible();
    expect(
      within(await panel("Shortages")).getByText("No draft is short of anything."),
    ).toBeVisible();
  });

  it("says nothing has changed yet in the activity panel", async () => {
    respondWithTiedUpParts([RESISTOR]);
    respondWithShortRevisions([]);
    respondWithActivity([]);
    renderDashboard();

    expect(
      await within(await panel("Recent activity")).findByText("Nothing has changed yet."),
    ).toBeVisible();
  });

  it("shows each panel's error on its own, the others still read", async () => {
    server.use(
      http.get("*/api/projects/holdings", () => HttpResponse.json({}, { status: 500 })),
      http.get("*/api/projects/shortages", () => HttpResponse.json({}, { status: 500 })),
      http.get("*/api/history", () => HttpResponse.json({}, { status: 500 })),
    );
    renderDashboard();

    expect(await within(await panel("Tied up in builds")).findByRole("alert")).toHaveTextContent(
      "The parts in builds couldn't be loaded.",
    );
    expect(await within(await panel("Shortages")).findByRole("alert")).toHaveTextContent(
      "The shortages couldn't be loaded.",
    );
    expect(await within(await panel("Recent activity")).findByRole("alert")).toHaveTextContent(
      "The activity couldn't be loaded.",
    );
  });

  it("shows each panel loading until its read answers", async () => {
    const never = async () => {
      await delay("infinite");
      return HttpResponse.json({});
    };
    server.use(
      http.get("*/api/projects/holdings", never),
      http.get("*/api/projects/shortages", never),
      http.get("*/api/history", never),
    );
    renderDashboard();

    expect(await screen.findByText("Loading the parts in builds…")).toBeVisible();
    expect(screen.getByText("Loading the shortages…")).toBeVisible();
    expect(screen.getByText("Loading the activity…")).toBeVisible();
  });

  it("reads every panel again when the dashboard is shown again", async () => {
    // Requirement 5.3: a build moved or a BOM changed elsewhere shows on the way back.
    const tiedUpReads = respondWithTiedUpParts([RESISTOR]);
    const shortageReads = respondWithShortRevisions([SHORT]);
    respondWithActivity([aChange()]);
    renderDashboard();
    const user = userEvent.setup();

    await user.click(
      await within(await panel("Recent activity")).findByRole("link", { name: "All activity" }),
    );
    expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    await user.click(within(nav).getByRole("link", { name: "Dashboard" }));

    expect(await screen.findByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expect.poll(() => tiedUpReads.length).toBe(2);
    await expect.poll(() => shortageReads.length).toBe(2);
  });

  it("speaks Brazilian Portuguese", async () => {
    respondWithTiedUpParts([RESISTOR]);
    respondWithShortRevisions([SHORT]);
    respondWithActivity([aChange()]);
    renderDashboard("pt-BR");

    expect(await screen.findByRole("heading", { name: "Painel", level: 1 })).toBeVisible();
    const tiedUp = await panel("Presas em montagens");
    expect(await within(tiedUp).findByText("3 reservadas · 5 em montagens")).toBeVisible();
    const shortages = await panel("Faltas");
    expect(await within(shortages).findByText("2 peças em falta")).toBeVisible();
    expect(shortages).toHaveTextContent("faltam 3");
    expect(shortages).toHaveTextContent("precisa de 4, 1 em estoque");
    const activity = await panel("Atividade recente");
    expect(within(activity).getByRole("link", { name: "Toda a atividade" })).toBeVisible();
  });
});

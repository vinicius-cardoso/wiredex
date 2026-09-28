import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aProject,
  aRevision,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithProject,
} from "../../test/server";

const PROJECT_ID = "0199eeee-0000-7000-8000-000000000001";
const breadboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000a",
  label: "A",
  summary: "breadboard",
  notes: "Sensor on jumper wires.\nPower from USB.",
});
const perfboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000b",
  label: "B",
  summary: "perfboard",
  forked_from: breadboard.id,
  created_at: "2026-09-27T11:00:00Z",
});
const weatherStation = aProject({
  id: PROJECT_ID,
  description: "A BME280 on an ESP32.\nLogs every five minutes.",
  tags: ["esp32", "i2c"],
  revisions: [breadboard, perfboard],
  latest_revision_id: perfboard.id,
  next_label: "C",
});

function renderAt(path: string) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithProject(weatherStation);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return router;
}

function revisionsNav() {
  return screen.getByRole("navigation", { name: "Revisions" });
}

describe("ProjectPage", () => {
  it("opens the latest revision when the address names none", async () => {
    renderAt(`/projects/${PROJECT_ID}`);

    expect(
      await screen.findByRole("heading", { name: "Weather station", level: 1 }),
    ).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Revision B – perfboard" });
    expect(panel).toHaveTextContent("Draft");
    expect(within(panel).getByRole("link", { name: "A" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/revisions/${breadboard.id}`,
    );
    expect(within(panel).getByText("No notes yet.")).toBeInTheDocument();
    expect(
      within(revisionsNav()).getByRole("link", { name: "B – perfboard · Draft" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(revisionsNav()).getByRole("link", { name: "A – breadboard · Draft" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("shows the header: tags linking to the filtered list and the description as written", async () => {
    renderAt(`/projects/${PROJECT_ID}`);

    const tags = await screen.findByRole("list", { name: "Tags" });
    expect(within(tags).getByRole("link", { name: "esp32" })).toHaveAttribute(
      "href",
      "/projects?tag=%5B%22esp32%22%5D",
    );
    expect(
      screen.getByText(/A BME280 on an ESP32\.\s+Logs every five minutes\./),
    ).toBeInTheDocument();
  });

  it("opens the revision its address names, and moves the mark with a link", async () => {
    renderAt(`/projects/${PROJECT_ID}/revisions/${breadboard.id}`);

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    expect(panel).toHaveTextContent(/Sensor on jumper wires\.\s+Power from USB\./);
    expect(panel).not.toHaveTextContent("Forked from");
    expect(
      within(revisionsNav()).getByRole("link", { name: "A – breadboard · Draft" }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent
      .setup()
      .click(within(revisionsNav()).getByRole("link", { name: "B – perfboard · Draft" }));

    expect(
      await screen.findByRole("region", { name: "Revision B – perfboard" }),
    ).toBeInTheDocument();
    expect(
      within(revisionsNav()).getByRole("link", { name: "B – perfboard · Draft" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("says so for a revision the project doesn't have, and links to the latest", async () => {
    renderAt(`/projects/${PROJECT_ID}/revisions/0199eeee-0000-7000-8000-0000000000ff`);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This project has no such revision.",
    );
    expect(screen.getByRole("link", { name: "Open the latest, B – perfboard" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/revisions/${perfboard.id}`,
    );
  });

  it("says so when the project can't be loaded", async () => {
    renderAt("/projects/0199eeee-0000-7000-8000-0000000000ff");

    expect(await screen.findByRole("alert")).toHaveTextContent("The project couldn't be loaded.");
  });
});

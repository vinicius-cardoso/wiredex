import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptProjectWrites,
  anAttachment,
  aProject,
  aRevision,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithAttachments,
  respondWithProject,
  respondWithProjects,
  respondWithProjectTags,
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

/** WRITABLE answers the page from `acceptProjectWrites`, which the test has set up itself. */
function renderAt(path: string, { writable = false } = {}) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  if (!writable) respondWithProject(weatherStation);
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

  it("shows the project's photos and the open revision's own files", async () => {
    renderAt(`/projects/${PROJECT_ID}`);
    respondWithAttachments(`revision:${perfboard.id}`, [
      anAttachment({
        subject: `revision:${perfboard.id}`,
        kind: "gerbers",
        title: "Perfboard gerbers",
        media_type: "application/zip",
      }),
    ]);

    expect(await screen.findByRole("heading", { name: "Photos", level: 2 })).toBeInTheDocument();
    expect(await screen.findByText("No photos yet.")).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Revision B – perfboard" });
    expect(within(panel).getByRole("heading", { name: "Files", level: 3 })).toBeInTheDocument();
    expect(await within(panel).findByText("Perfboard gerbers")).toBeInTheDocument();
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

  it("edits the project in place and shows the saved details", async () => {
    const writes = acceptProjectWrites(weatherStation);
    respondWithProjectTags([]);
    renderAt(`/projects/${PROJECT_ID}`, { writable: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit project" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Weather station");
    await user.clear(name);
    await user.type(name, "Weather station mk2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("heading", { name: "Weather station mk2", level: 1 }),
    ).toBeInTheDocument();
    expect(writes.edits).toEqual([
      {
        name: "Weather station mk2",
        description: "A BME280 on an ESP32.\nLogs every five minutes.",
        tags: ["esp32", "i2c"],
      },
    ]);
    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
  });

  it("deletes the project after asking, and lands on the list", async () => {
    acceptProjectWrites(weatherStation);
    respondWithProjects([]);
    respondWithProjectTags([]);
    const router = renderAt(`/projects/${PROJECT_ID}`, { writable: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete project" }));
    const question = screen.getByRole("group", {
      name: "Delete Weather station and all its revisions?",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(await screen.findByRole("heading", { name: "Projects", level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/projects");
  });

  it("shows the API's sentence when a revision keeps the project", async () => {
    acceptProjectWrites(weatherStation, {
      refuseProjectDelete: "revision A is built, and only a draft can be deleted",
    });
    renderAt(`/projects/${PROJECT_ID}`, { writable: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete project" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete it" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "revision A is built, and only a draft can be deleted",
    );
    expect(screen.getByRole("heading", { name: "Weather station", level: 1 })).toBeInTheDocument();
  });

  it("adds a revision with the suggested label and opens it", async () => {
    const writes = acceptProjectWrites(weatherStation);
    const router = renderAt(`/projects/${PROJECT_ID}`, { writable: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "New revision" }));
    const dialog = screen.getByRole("dialog", { name: "New revision of Weather station" });
    expect(within(dialog).getByRole("textbox", { name: "Label" })).toHaveValue("C");
    await user.type(within(dialog).getByRole("textbox", { name: "Summary" }), "first PCB");
    await user.click(within(dialog).getByRole("button", { name: "Add revision" }));

    expect(
      await screen.findByRole("region", { name: "Revision C – first PCB" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes.additions).toEqual([{ label: "C", summary: "first PCB", notes: null }]);
    const added = writes.project()?.revisions.at(-1);
    expect(router.state.location.pathname).toBe(`/projects/${PROJECT_ID}/revisions/${added?.id}`);
    expect(
      within(revisionsNav()).getByRole("link", { name: "C – first PCB · Draft" }),
    ).toHaveAttribute("aria-current", "page");
  });
});

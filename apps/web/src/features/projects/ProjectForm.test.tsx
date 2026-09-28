import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptProjectCreates,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithProjects,
  respondWithProjectTags,
} from "../../test/server";

function renderNewProject(taken: string[] = []) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithProjects([]);
  respondWithProjectTags([{ tag: "esp32", projects: 1 }]);
  const sent = acceptProjectCreates(taken);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(
    queryClient,
    createMemoryHistory({ initialEntries: ["/projects/new"] }),
  );
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router, sent };
}

describe("NewProjectPage", () => {
  it("saves the project and opens it on revision A", async () => {
    const { router, sent } = renderNewProject();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("textbox", { name: "Name" }), "  Weather   station ");
    await user.type(
      screen.getByRole("textbox", { name: "Description" }),
      "A BME280 on an ESP32.{Enter}Logs every five minutes.",
    );
    await user.type(screen.getByRole("combobox", { name: "Tags" }), "ESP32{Enter}i2c,");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("region", { name: "Revision A" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Weather station", level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/projects/0199eeee-0000-7000-8000-0000000000f1");
    expect(sent).toEqual([
      {
        name: "Weather station",
        description: "A BME280 on an ESP32.\nLogs every five minutes.",
        tags: ["esp32", "i2c"],
      },
    ]);
  });

  it("sends a blank description as none", async () => {
    const { sent } = renderNewProject();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("textbox", { name: "Name" }), "Greenhouse");
    await user.type(screen.getByRole("textbox", { name: "Description" }), "   ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ name: "Greenhouse", description: null, tags: [] });
  });

  it("asks for a name before sending anything", async () => {
    const { sent } = renderNewProject();
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.type(name, "   ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("A project needs a name.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("A project needs a name.");
    expect(sent).toEqual([]);
  });

  it("refuses a name over 120 characters", async () => {
    const { sent } = renderNewProject();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("textbox", { name: "Name" }));
    await user.paste("x".repeat(121));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("At most 120 characters.")).toBeInTheDocument();
    expect(sent).toEqual([]);
  });

  it("puts a name another project holds on the name", async () => {
    const { router } = renderNewProject(["weather station"]);
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.type(name, "Weather station");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(name).toHaveAccessibleDescription("there is already a project named Weather station"),
    );
    expect(router.state.location.pathname).toBe("/projects/new");
  });

  it("goes back to the list on Cancel", async () => {
    const { router } = renderNewProject();

    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/projects"));
  });
});

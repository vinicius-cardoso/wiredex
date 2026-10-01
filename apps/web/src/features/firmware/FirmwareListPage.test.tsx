import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Language } from "@wiredex/i18n";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aFirmwareSummary,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithFirmwareList,
} from "../../test/server";

const weatherStation = aFirmwareSummary({
  name: "Weather station",
  target: "esp32:esp32:esp32",
  framework: "arduino",
  latest_release: { id: "0199ffff-0000-7000-8000-0000000000b2", version: "1.1.0" },
  versions: 3,
  drafts: 1,
  updated_at: "2026-09-30T12:00:00Z",
});
const picoBlink = aFirmwareSummary({
  id: "0199ffff-0000-7000-8000-000000000002",
  name: "Pico blink",
  target: "RPI_PICO",
  framework: "micropython",
  latest_release: null,
  versions: 1,
  drafts: 1,
  updated_at: "2026-09-29T09:00:00Z",
});

function renderListPage(
  initial = "/firmware",
  firmware = [weatherStation, picoBlink],
  language: Language = "en",
) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const asked = respondWithFirmwareList(firmware);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [initial] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient, language });
  return { router, asked };
}

function firmwareNames(): string[] {
  return screen.queryAllByRole("rowheader").map((cell) => cell.textContent ?? "");
}

describe("FirmwareListPage", () => {
  it("lists each firmware with its target, framework, latest release and last change", async () => {
    renderListPage();

    const link = await screen.findByRole("link", { name: "Weather station" });
    expect(link).toHaveAttribute("href", `/firmware/${weatherStation.id}`);
    expect(firmwareNames()).toEqual(["Weather station", "Pico blink"]);
    const row = link.closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("esp32:esp32:esp32");
    expect(row).toHaveTextContent("Arduino");
    expect(row).toHaveTextContent("1.1.0");
    expect(row).toHaveTextContent("3 versions");
    expect(row).toHaveTextContent("1 draft");
    expect(within(row).getByText("Sep 30, 2026")).toHaveAttribute(
      "datetime",
      weatherStation.updated_at,
    );
    const pico = screen.getByRole("link", { name: "Pico blink" }).closest("tr") as HTMLElement;
    expect(pico).toHaveTextContent("MicroPython");
    expect(pico).toHaveTextContent("None yet");
    expect(pico).toHaveTextContent("1 version");
    expect(screen.getByRole("link", { name: "New firmware" })).toHaveAttribute(
      "href",
      "/firmware/new",
    );
  });

  it("writes the search to the address once typing pauses, and asks the API for it", async () => {
    const { router, asked } = renderListPage();
    await screen.findByRole("link", { name: "Weather station" });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search firmware by name or board" }), "pico");

    await waitFor(() => expect(router.state.location.search).toEqual({ q: "pico" }));
    await waitFor(() => expect(firmwareNames()).toEqual(["Pico blink"]));
    expect(asked.at(-1)?.get("search")).toBe("pico");
  });

  it("reads the search from the address, matching a board target too", async () => {
    renderListPage("/firmware?q=esp32");

    await waitFor(() => expect(firmwareNames()).toEqual(["Weather station"]));
    expect(screen.getByRole("searchbox", { name: "Search firmware by name or board" })).toHaveValue(
      "esp32",
    );
  });

  it("offers to clear the search when nothing matches", async () => {
    const { router } = renderListPage("/firmware?q=nowhere");

    expect(await screen.findByText("No firmware matches this search.")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Clear the search" }));

    await waitFor(() => expect(router.state.location.search).toEqual({}));
    expect(await screen.findByRole("link", { name: "Weather station" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search firmware by name or board" })).toHaveValue(
      "",
    );
  });

  it("says a new firmware has no version in words, which Portuguese needs", async () => {
    // Portuguese counts 0 as singular, so a bare count would read "0 versão".
    renderListPage("/firmware", [aFirmwareSummary({ name: "Greenhouse controller" })], "pt-BR");

    const link = await screen.findByRole("link", { name: "Greenhouse controller" });
    const row = link.closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Nenhuma versão");
    expect(row).not.toHaveTextContent("0 versão");
  });

  it("invites a first firmware when there is none", async () => {
    renderListPage("/firmware", []);

    expect(
      await screen.findByText("No firmware yet. Start one for the next board you flash."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear the search" })).not.toBeInTheDocument();
  });
});

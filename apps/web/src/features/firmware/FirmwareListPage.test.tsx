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

  it("narrows by framework and by whether a release exists, kept in the address", async () => {
    const { router } = renderListPage();
    const user = userEvent.setup();
    await screen.findByRole("link", { name: "Weather station" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Framework" }), "MicroPython");

    await waitFor(() => expect(firmwareNames()).toEqual(["Pico blink"]));
    expect(router.state.location.search).toEqual({ framework: "micropython" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Release" }), "Has a release");

    expect(await screen.findByText("No firmware matches this search.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear the search" }));
    await waitFor(() => expect(firmwareNames()).toEqual(["Weather station", "Pico blink"]));
  });

  it("narrows by a board target fragment, case aside, once typing pauses", async () => {
    const { router, asked } = renderListPage();
    const user = userEvent.setup();
    await screen.findByRole("link", { name: "Weather station" });

    await user.type(screen.getByRole("textbox", { name: "Board target" }), "pico");

    await waitFor(() => expect(firmwareNames()).toEqual(["Pico blink"]));
    expect(router.state.location.search).toEqual({ target: "pico" });
    // The target narrows the list on hand; the API is asked for no other search.
    expect(asked.every((params) => !params.get("search"))).toBe(true);

    await user.click(screen.getByRole("button", { name: "Clear the search" }));
    await waitFor(() => expect(firmwareNames()).toEqual(["Weather station", "Pico blink"]));
    expect(screen.getByRole("textbox", { name: "Board target" })).toHaveValue("");
  });

  it("keeps the board target beside a framework from the address", async () => {
    renderListPage("/firmware?target=esp32&framework=micropython");

    expect(await screen.findByText("No firmware matches this search.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Board target" })).toHaveValue("esp32");
  });

  it("opens already narrowed from a link that names a framework", async () => {
    renderListPage("/firmware?framework=arduino");

    await waitFor(() => expect(firmwareNames()).toEqual(["Weather station"]));
    expect(screen.getByRole("combobox", { name: "Framework" })).toHaveValue("arduino");
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

  describe("in pages", () => {
    // Sixty firmware, every other one for MicroPython, so 50 a page makes two pages.
    const many = Array.from({ length: 60 }, (_, index) => {
      const number = String(index + 1).padStart(2, "0");
      return aFirmwareSummary({
        id: `0199ffff-0000-7000-8000-0000000001${number}`,
        name: `Firmware ${number}`,
        framework: index % 2 === 0 ? "arduino" : "micropython",
      });
    });

    function pages() {
      return screen.getByRole("navigation", { name: "Pages of the firmware list" });
    }

    it("shows 50 at a time, with the page in the address and Back to the one before", async () => {
      const { router } = renderListPage("/firmware", many);
      const bar = await screen.findByRole("navigation", { name: "Pages of the firmware list" });
      expect(await within(bar).findByText("1–50 of 60")).toBeInTheDocument();
      expect(firmwareNames()).toHaveLength(50);

      await userEvent.setup().click(within(pages()).getByRole("button", { name: "Page 2" }));

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 2 }));
      expect(firmwareNames()).toEqual(many.slice(50).map((item) => item.name));

      router.history.back();

      await waitFor(() => expect(firmwareNames()).toHaveLength(50));
      expect(router.state.location.search).toEqual({});
    });

    it("pages what the filters leave, and starts again at page 1 at the size chosen", async () => {
      const { router } = renderListPage("/firmware?page=2&size=25", many);
      const bar = await screen.findByRole("navigation", { name: "Pages of the firmware list" });
      expect(await within(bar).findByText("26–50 of 60")).toBeInTheDocument();

      await userEvent
        .setup()
        .selectOptions(screen.getByRole("combobox", { name: "Framework" }), "MicroPython");

      await waitFor(() =>
        expect(router.state.location.search).toEqual({ framework: "micropython", size: 25 }),
      );
      expect(within(pages()).getByText("1–25 of 30")).toBeInTheDocument();
      expect(firmwareNames()[0]).toBe("Firmware 02");
    });

    it("opens the last page for one past the end", async () => {
      const { router } = renderListPage("/firmware?page=5", many);

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 2 }));
      expect(within(pages()).getByText("51–60 of 60")).toBeInTheDocument();
    });
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

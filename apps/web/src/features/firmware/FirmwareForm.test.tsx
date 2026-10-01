import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { acceptFirmwareWrites, aFirmware, server } from "../../test/server";
import { FirmwareForm } from "./FirmwareForm";

async function fillAndSave(name: string, target: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "Name" }), name);
  await user.type(screen.getByRole("textbox", { name: "Board target" }), target);
  await user.click(screen.getByRole("button", { name: "Save" }));
}

describe("FirmwareForm", () => {
  it("marks the API's refusal on the field it names, in the reader's language", async () => {
    server.use(
      http.post("*/api/firmware", () =>
        HttpResponse.json(
          {
            detail: {
              message: "a board target holds no control character",
              code: "invalid_target",
              field: "target",
              item: null,
            },
          },
          { status: 422 },
        ),
      ),
    );
    const onSaved = vi.fn();
    renderWithProviders(<FirmwareForm onSaved={onSaved} />);

    await fillAndSave("Weather station", "esp32:esp32:esp32");

    const target = screen.getByRole("textbox", { name: "Board target" });
    expect(
      await screen.findByText(
        "This board target isn't accepted: keep it to 200 characters, with no control characters.",
      ),
    ).toBeInTheDocument();
    expect(target).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("textbox", { name: "Name" })).not.toHaveAttribute("aria-invalid");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("says the revision is gone when a new firmware for it is refused with a 404", async () => {
    const writes = acceptFirmwareWrites([], { revisions: [] });
    const onSaved = vi.fn();
    renderWithProviders(
      <FirmwareForm revisionId="0199eeee-0000-7000-8000-00000000000a" onSaved={onSaved} />,
    );

    await fillAndSave("Weather station", "esp32:esp32:esp32");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That revision is no longer in this workspace, so nothing was saved.",
    );
    expect(writes.creates).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("says the firmware is gone when an edit is refused with a 404", async () => {
    acceptFirmwareWrites([]);
    const onSaved = vi.fn();
    renderWithProviders(<FirmwareForm firmware={aFirmware()} onSaved={onSaved} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This firmware is no longer in this workspace, so nothing was saved.",
    );
    expect(onSaved).not.toHaveBeenCalled();
  });
});

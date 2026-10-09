import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V110,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../../test/firmware";
import { renderInRouter } from "../../../test/render";
import {
  acceptFirmwareWrites,
  acceptFlashWrites,
  anAttachment,
  aUnit,
  aUnitFirmware,
  respondWithAttachments,
  respondWithBoards,
  respondWithUnitSearch,
  server,
} from "../../../test/server";
import { aBuildZip } from "../../../test/zip";
import { CurrentFirmware } from "../FlashLogSection";
import type { Flasher, WriteOptions } from "./flasher";
import type { PlacedImage } from "./images";
import { buildsSubject } from "./useStoredBuild";

const serial = vi.hoisted(() => ({
  serialSupported: vi.fn(),
  choosePort: vi.fn(),
  connect: vi.fn(),
}));
vi.mock("./flasher", () => serial);

const station = weatherStationWith([v120, v110, v100]);
const unit = aUnit();
const port = {} as SerialPort;

const app = () => new File([new Uint8Array(0x3000)], "weather.ino.bin");
const bootloader = () => new File([new Uint8Array(0x5000)], "weather.ino.bootloader.bin");

type Write = (images: PlacedImage[], options: WriteOptions) => Promise<void>;

function aFlasher(write: Write = async () => {}) {
  const flasher = {
    chip: {
      name: "ESP32-D0WD-V3",
      mac: "a0:b7:65:4c:1d:20",
      bootloaderOffset: 0x1000,
      flashBytes: 4 * 1024 * 1024,
    },
    write: vi.fn(write),
    restart: vi.fn(async () => {}),
    release: vi.fn(async () => {}),
  } satisfies Flasher;
  serial.connect.mockResolvedValue(flasher);
  return flasher;
}

const build = anAttachment({
  id: "0199eeee-0000-7000-8000-0000000000b1",
  subject: buildsSubject(V110),
  kind: "firmware_build",
  title: "Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1",
  media_type: "application/zip",
  size: 174_352,
});

/** Version 1.1.0 holding one build, whose zip is ZIP. */
function storeBuild(zip: Uint8Array) {
  server.use(
    http.get("*/api/files/attachments/:id/content", () =>
      HttpResponse.arrayBuffer(zip.buffer as ArrayBuffer, {
        headers: { "Content-Type": "application/zip" },
      }),
    ),
  );
  return [build];
}

const builtImages = [
  { file: "weather.ino.bootloader.bin", offset: 0x1000, data: new Uint8Array(0x5000) },
  { file: "boot_app0.bin", offset: 0xe000, data: new Uint8Array(0x2000) },
  { file: "weather.ino.bin", offset: 0x10000, data: new Uint8Array(0x3000) },
];

type Opening = { supported?: boolean; builds?: (typeof build)[] };

/** The dialog opened from a unit's page, on Weather station 1.1.0, its highest release. */
async function openOnUnit({ supported = true, builds = [] }: Opening = {}) {
  serial.serialSupported.mockReturnValue(supported);
  respondWithAttachments(buildsSubject(V110), builds);
  acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
  const writes = acceptFlashWrites(aUnitFirmware(), { firmware: [station] });
  renderInRouter(<CurrentFirmware unit={unit} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Flash from the browser" }));
  const dialog = screen.getByRole("dialog", { name: "Flash WX-U-0001 from the browser" });
  if (supported) {
    await within(dialog).findByRole("combobox", { name: "Version" });
    // The version's build is looked up first: the binaries show once that is known.
    await waitFor(() =>
      expect(within(dialog).queryByText("Looking for this version's build…")).toBeNull(),
    );
  }
  return { writes, user, dialog };
}

beforeEach(() => {
  serial.choosePort.mockResolvedValue(port);
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("WriteFlashForm", () => {
  it("writes the binaries at their offsets, then logs the flash as now", async () => {
    let finish = () => {};
    const flasher = aFlasher(async (_images, { onProgress }) => {
      onProgress({ file: 1, written: 512, total: 1024 });
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const { writes, user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), [app(), bootloader()]);
    expect(await within(dialog).findByLabelText("Offset of weather.ino.bin")).toHaveValue(
      "0x10000",
    );
    expect(within(dialog).getByLabelText("Offset of weather.ino.bootloader.bin")).toHaveValue(
      "0x1000",
    );
    await user.type(within(dialog).getByRole("textbox", { name: "Notes" }), " Bench  test ");
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    // Half of the second binary, the app, after the whole bootloader: 0x5000 + 0x1800 of 0x8000.
    const progress = await within(dialog).findByRole("progressbar", { name: "Written so far" });
    expect(progress).toHaveValue(0.8125);
    expect(within(dialog).getByRole("status")).toHaveTextContent("Writing weather.ino.bin…");
    // A write isn't left half done: nothing closes the dialog or changes what is flashed.
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(within(dialog).getByRole("combobox", { name: "Version" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(dialog).toBeInTheDocument();
    expect(writes.logged).toEqual([]);

    finish();
    expect(
      await within(dialog).findByText(
        "ESP32-D0WD-V3 is flashed, every binary read back as it was sent, and the flash is logged.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("a0:b7:65:4c:1d:20")).toBeInTheDocument();
    expect(serial.connect).toHaveBeenCalledWith(port, expect.any(Function));
    const [images, options] = flasher.write.mock.calls[0] ?? [];
    expect(images?.map((image) => [image.name, image.address, image.bytes.length])).toEqual([
      ["weather.ino.bootloader.bin", 0x1000, 0x5000],
      ["weather.ino.bin", 0x10000, 0x3000],
    ]);
    expect(options?.eraseAll).toBe(false);
    expect(flasher.restart).toHaveBeenCalledOnce();
    expect(writes.logged).toEqual([
      { unitId: unit.id, body: { version_id: V110, flashed_at: null, notes: "Bench test" } },
    ]);

    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // The unit's block reads the log again, so it shows what the board now runs.
    expect(await screen.findByRole("link", { name: "1.1.0" })).toBeInTheDocument();
  });

  it("asks for binaries that sit apart on sector starts before touching a port", async () => {
    aFlasher();
    const { user, dialog } = await openOnUnit();
    const submit = within(dialog).getByRole("button", { name: "Connect and flash" });

    await user.click(submit);
    expect(within(dialog).getByText("Add at least one binary.")).toBeInTheDocument();

    await user.upload(within(dialog).getByLabelText("Binaries"), [
      app(),
      new File([new Uint8Array(0x1000)], "littlefs.bin"),
      new File([], "empty.bin"),
    ]);
    const offset = await within(dialog).findByLabelText("Offset of weather.ino.bin");
    await user.clear(offset);
    await user.type(offset, "0x10010");
    await user.click(submit);

    expect(offset).toHaveAttribute("aria-invalid", "true");
    expect(offset).toHaveAccessibleDescription(
      "Enter where a flash sector starts: a multiple of 0x1000, such as 0x10000.",
    );
    expect(within(dialog).getByLabelText("Offset of empty.bin")).toHaveAccessibleDescription(
      "This file is empty.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Remove empty.bin" }));
    await user.clear(offset);
    await user.type(offset, "0x10000");
    // Both suggested at the app's offset: the second would erase the first.
    expect(within(dialog).getByLabelText("Offset of littlefs.bin")).toHaveAccessibleDescription(
      "This binary would land on weather.ino.bin.",
    );
    await user.click(submit);
    expect(serial.choosePort).not.toHaveBeenCalled();

    const data = within(dialog).getByLabelText("Offset of littlefs.bin");
    await user.clear(data);
    await user.type(data, "0x290000");
    await user.click(within(dialog).getByRole("checkbox", { name: "Erase the whole flash first" }));
    await user.click(submit);
    await within(dialog).findByText(/and the flash is logged/);
    expect(serial.connect.mock.results).toHaveLength(1);
  });

  it("stays as it is when the browser's chooser is closed without a port", async () => {
    const flasher = aFlasher();
    serial.choosePort.mockResolvedValue(null);
    const { user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    await waitFor(() => expect(serial.choosePort).toHaveBeenCalledOnce());
    expect(serial.connect).not.toHaveBeenCalled();
    expect(flasher.write).not.toHaveBeenCalled();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();

    serial.choosePort.mockRejectedValue(new DOMException("Blocked", "SecurityError"));
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The browser didn't allow a serial port.",
    );
  });

  it("says how to wake a board that doesn't answer, and lets it be tried again", async () => {
    serial.connect.mockRejectedValue(new Error("Failed to connect with the device"));
    const { writes, user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The board didn't answer. Close anything else using its port, such as a serial monitor, then try again holding its BOOT button.",
    );
    expect(writes.logged).toEqual([]);

    aFlasher();
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    await within(dialog).findByText(/and the flash is logged/);
  });

  it("writes nothing when the bootloader isn't where the chip that answered starts", async () => {
    const flasher = aFlasher();
    flasher.chip.name = "ESP32-S3";
    flasher.chip.bootloaderOffset = 0;
    const { writes, user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), bootloader());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "ESP32-S3 starts from 0x0, but weather.ino.bootloader.bin is set to 0x1000. Nothing was written: fix the offset and flash again.",
    );
    expect(flasher.write).not.toHaveBeenCalled();
    expect(flasher.release).toHaveBeenCalledOnce();
    expect(writes.logged).toEqual([]);
  });

  it("writes nothing past the end of the chip's flash", async () => {
    const flasher = aFlasher();
    const { user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    const offset = await within(dialog).findByLabelText("Offset of weather.ino.bin");
    await user.clear(offset);
    await user.type(offset, "0x3fe000");
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "weather.ino.bin runs past the end of this board's 4.0 MB of flash. Nothing was written.",
    );
    expect(flasher.write).not.toHaveBeenCalled();
  });

  it("logs nothing when the write fails, and shows what the loader said", async () => {
    serial.connect.mockImplementation(async (_port, log: (line: string) => void) => {
      log("Chip is ESP32-D0WD-V3");
      return aFlasher(async () => {
        throw new Error("MD5 of file does not match data in flash!");
      });
    });
    const { writes, user, dialog } = await openOnUnit();

    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The write stopped: MD5 of file does not match data in flash!. The board may not start until it is flashed again.",
    );
    expect(within(dialog).getByText("Loader output")).toBeInTheDocument();
    expect(within(dialog).getByText("Chip is ESP32-D0WD-V3")).toBeInTheDocument();
    expect(writes.logged).toEqual([]);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("keeps a written board to log again when logging it is refused", async () => {
    const flasher = aFlasher();
    flasher.restart.mockRejectedValue(new Error("port lost"));
    const { writes, user, dialog } = await openOnUnit();
    server.use(
      http.post(
        "*/api/firmware/units/:unitId/flashes",
        () => HttpResponse.json({ detail: "down" }, { status: 503 }),
        { once: true },
      ),
    );

    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The flash couldn't be logged. The flash couldn't be logged.",
    );
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "ESP32-D0WD-V3 is flashed, and every binary read back as it was sent.",
    );
    expect(writes.logged).toEqual([]);

    await user.click(within(dialog).getByRole("button", { name: "Log it again" }));
    await within(dialog).findByText(/and the flash is logged/);
    expect(flasher.write).toHaveBeenCalledOnce();
    expect(writes.logged).toEqual([
      { unitId: unit.id, body: { version_id: V110, flashed_at: null, notes: null } },
    ]);
  });

  it("flashes the version's stored build with no file chosen", async () => {
    const flasher = aFlasher();
    const { writes, user, dialog } = await openOnUnit({
      builds: storeBuild(aBuildZip(builtImages)),
    });

    // The build in place of the file picker: its name, its binaries and their offsets.
    expect(
      await within(dialog).findByText("Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1"),
    ).toBeInTheDocument();
    expect(dialog.querySelector('input[type="file"]')).toBeNull();
    const listed = within(within(dialog).getByRole("list", { name: "Binaries" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(listed).toEqual([
      "weather.ino.bootloader.bin20.0 KBat 0x1000",
      "boot_app0.bin8.0 KBat 0xe000",
      "weather.ino.bin12.0 KBat 0x10000",
    ]);

    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    await within(dialog).findByText(/and the flash is logged/);
    const [images] = flasher.write.mock.calls[0] ?? [];
    expect(images?.map((image) => [image.name, image.address, image.bytes.length])).toEqual([
      ["weather.ino.bootloader.bin", 0x1000, 0x5000],
      ["boot_app0.bin", 0xe000, 0x2000],
      ["weather.ino.bin", 0x10000, 0x3000],
    ]);
    expect(writes.logged).toEqual([
      { unitId: unit.id, body: { version_id: V110, flashed_at: null, notes: null } },
    ]);
  });

  it("takes files from the computer instead of the stored build, and goes back", async () => {
    const flasher = aFlasher();
    const { user, dialog } = await openOnUnit({ builds: storeBuild(aBuildZip(builtImages)) });

    await user.click(
      await within(dialog).findByRole("button", {
        name: "Choose files from this computer instead",
      }),
    );
    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    expect(await within(dialog).findByLabelText("Offset of weather.ino.bin")).toBeEnabled();
    expect(within(dialog).queryByText("boot_app0.bin")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Use this version's build" }));
    expect(within(dialog).getByText("boot_app0.bin")).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: "Choose files from this computer instead" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    await within(dialog).findByText(/and the flash is logged/);
    // The file chosen before is still there, and it alone is written.
    expect(flasher.write.mock.calls[0]?.[0].map((image) => image.name)).toEqual([
      "weather.ino.bin",
    ]);
  });

  it("checks a stored build as it checks chosen files, and says what it was built for", async () => {
    const flasher = aFlasher();
    const overlapping = [
      { file: "app.bin", offset: 0x10000, data: new Uint8Array(0x3000) },
      { file: "data.bin", offset: 0x11000, data: new Uint8Array(0x1000) },
    ];
    const zip = aBuildZip(overlapping, { board: "esp32:esp32:esp32s3" });
    const { user, dialog } = await openOnUnit({ builds: storeBuild(zip) });

    expect(
      await within(dialog).findByText(
        "Built for esp32:esp32:esp32s3; this firmware's board is now esp32:esp32:esp32.",
      ),
    ).toBeInTheDocument();
    // Shown at once: no offset can be typed over to fix it.
    expect(within(dialog).getByText("This binary would land on app.bin.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    expect(serial.choosePort).not.toHaveBeenCalled();
    expect(flasher.write).not.toHaveBeenCalled();
  });

  it("says why a stored build can't be flashed, and offers the computer's files", async () => {
    aFlasher();
    const zip = aBuildZip(builtImages, {
      images: [{ file: "weather.ino.merged.bin", offset: 0 }],
    });
    const { user, dialog } = await openOnUnit({ builds: storeBuild(zip) });

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1 can't be flashed from here. Its manifest names weather.ino.merged.bin, which the zip doesn't hold.",
    );
    await user.upload(within(dialog).getByLabelText("Binaries"), app());
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    await within(dialog).findByText(/and the flash is logged/);
  });

  it("says a build that can't be downloaded couldn't be, and that a version has none", async () => {
    aFlasher();
    server.use(
      http.get(
        "*/api/files/attachments/:id/content",
        () => new HttpResponse(null, { status: 503 }),
      ),
    );
    const { dialog } = await openOnUnit({ builds: [build] });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "can't be flashed from here. It couldn't be downloaded.",
    );
  });

  it("says a version has no build stored, beside the file picker", async () => {
    aFlasher();
    const { dialog } = await openOnUnit();
    expect(
      await within(dialog).findByText(
        "This version has no build stored. Choose its binaries here, or run wiredex firmware build to store one.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Binaries")).toBeInTheDocument();
  });

  it("says where it works in a browser without Web Serial", async () => {
    const { dialog } = await openOnUnit({ supported: false });

    expect(
      await within(dialog).findByText(
        /This browser can't reach a serial port\. Open Wiredex in Chrome/,
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Binaries")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Connect and flash" })).toBeNull();
  });

  it("flashes a released version onto the board the picker finds", async () => {
    aFlasher();
    serial.serialSupported.mockReturnValue(true);
    acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
    respondWithUnitSearch([unit]);
    respondWithAttachments(buildsSubject(V110), storeBuild(aBuildZip(builtImages)));
    const writes = acceptFlashWrites(aUnitFirmware(), { firmware: [station] });
    respondWithBoards(FIRMWARE_ID, () => []);
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V110}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.1.0" });
    await user.click(await within(panel).findByRole("button", { name: "Flash from the browser" }));
    const dialog = screen.getByRole("dialog", {
      name: "Flash Weather station 1.1.0 from the browser",
    });
    // The version is the dialog's own, so its build shows before a board is chosen.
    expect(await within(dialog).findByText("boot_app0.bin")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));
    const board = within(dialog).getByRole("combobox", { name: "Board" });
    expect(board).toHaveAccessibleDescription("Choose the board to flash.");
    expect(serial.choosePort).not.toHaveBeenCalled();

    await user.type(board, "WX-U");
    await user.click(await within(dialog).findByRole("option", { name: /WX-U-0001/ }));
    await user.click(within(dialog).getByRole("button", { name: "Connect and flash" }));

    await within(dialog).findByText(/and the flash is logged/);
    expect(writes.logged).toEqual([
      { unitId: unit.id, body: { version_id: V110, flashed_at: null, notes: null } },
    ]);
  });
});

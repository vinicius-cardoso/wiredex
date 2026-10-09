import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { choosePort, connect, serialSupported } from "./flasher";

const loader = {
  main: vi.fn(),
  writeFlash: vi.fn(),
  after: vi.fn(),
  detectFlashSize: vi.fn(),
  flashSizeBytes: (size: string) => Number.parseInt(size, 10) * 1024 * 1024,
  chip: { BOOTLOADER_FLASH_OFFSET: 0x1000, readMac: vi.fn() },
};
const disconnect = vi.fn();
const built: {
  baudrate: number;
  romBaudrate: number;
  terminal: { writeLine: (line: string) => void };
}[] = [];

vi.mock("esptool-js", () => ({
  Transport: class {
    disconnect = disconnect;
  },
  ESPLoader: class {
    constructor(options: (typeof built)[number]) {
      built.push(options);
      // biome-ignore lint/correctness/noConstructorReturn: the test's one loader stands in.
      return loader;
    }
  },
}));

const port = {} as SerialPort;

beforeEach(() => {
  loader.main.mockResolvedValue("ESP32-D0WD-V3 (revision v3.1)");
  loader.chip.readMac.mockResolvedValue("a0:b7:65:4c:1d:20");
  loader.detectFlashSize.mockResolvedValue("4MB");
  loader.writeFlash.mockResolvedValue(undefined);
  loader.after.mockResolvedValue(undefined);
  disconnect.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  built.length = 0;
});

describe("serialSupported", () => {
  it("is what the browser says", () => {
    expect(serialSupported()).toBe(false);
    vi.stubGlobal("navigator", { serial: {} });
    expect(serialSupported()).toBe(true);
  });
});

describe("choosePort", () => {
  it("gives the port chosen, and none when the chooser is closed", async () => {
    const requestPort = vi.fn().mockResolvedValueOnce(port);
    vi.stubGlobal("navigator", { serial: { requestPort } });
    await expect(choosePort()).resolves.toBe(port);

    requestPort.mockRejectedValueOnce(new DOMException("No port selected", "NotFoundError"));
    await expect(choosePort()).resolves.toBeNull();

    requestPort.mockRejectedValueOnce(new DOMException("Blocked", "SecurityError"));
    await expect(choosePort()).rejects.toThrow("Blocked");
  });
});

describe("connect", () => {
  it("reads what the chip is, passing the loader's lines on", async () => {
    const lines: string[] = [];
    const flasher = await connect(port, (line) => lines.push(line));

    expect(flasher.chip).toEqual({
      name: "ESP32-D0WD-V3 (revision v3.1)",
      mac: "a0:b7:65:4c:1d:20",
      flashBytes: 4 * 1024 * 1024,
      bootloaderOffset: 0x1000,
    });
    expect(built[0]).toMatchObject({ baudrate: 460_800, romBaudrate: 115_200 });
    built[0]?.terminal.writeLine("Chip is ESP32");
    expect(lines).toEqual(["Chip is ESP32"]);
  });

  it("does without what a locked chip won't say", async () => {
    loader.chip.readMac.mockRejectedValue(new Error("unsupported"));
    loader.detectFlashSize.mockRejectedValue(new Error("unsupported"));
    expect((await connect(port, () => {})).chip).toMatchObject({ mac: null, flashBytes: null });

    loader.detectFlashSize.mockResolvedValue(undefined);
    expect((await connect(port, () => {})).chip.flashBytes).toBeNull();
  });

  it("frees the port when the chip doesn't answer", async () => {
    loader.main.mockRejectedValue(new Error("Failed to connect with the device"));
    await expect(connect(port, () => {})).rejects.toThrow("Failed to connect");
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("writes each binary as built, compressed and checked against its MD5", async () => {
    const flasher = await connect(port, () => {});
    const bytes = new TextEncoder().encode("abc");
    const progress = vi.fn();

    await flasher.write([{ name: "app.bin", bytes, address: 0x10000 }], {
      eraseAll: true,
      onProgress: progress,
    });

    const options = loader.writeFlash.mock.calls[0]?.[0];
    expect(options).toMatchObject({
      fileArray: [{ data: bytes, address: 0x10000 }],
      flashMode: "keep",
      flashFreq: "keep",
      flashSize: "keep",
      eraseAll: true,
      compress: true,
    });
    expect(options.calculateMD5Hash(bytes)).toBe("900150983cd24fb0d6963f7d28e17f72");
    options.reportProgress(0, 512, 2048);
    expect(progress).toHaveBeenCalledWith({ file: 0, written: 512, total: 2048 });
  });

  it("resets into the new firmware and frees the port, even when the reset fails", async () => {
    const flasher = await connect(port, () => {});
    await flasher.restart();
    expect(loader.after).toHaveBeenCalledWith("hard_reset");
    expect(disconnect).toHaveBeenCalledOnce();

    loader.after.mockRejectedValue(new Error("port lost"));
    await expect(flasher.restart()).rejects.toThrow("port lost");
    expect(disconnect).toHaveBeenCalledTimes(2);
  });

  it("frees the port without a reset, whatever closing it says", async () => {
    const flasher = await connect(port, () => {});
    disconnect.mockRejectedValue(new Error("already closed"));
    await expect(flasher.release()).resolves.toBeUndefined();
    expect(loader.after).not.toHaveBeenCalled();
  });
});

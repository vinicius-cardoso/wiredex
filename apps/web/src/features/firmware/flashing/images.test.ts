import { describe, expect, it } from "vitest";
import {
  type FlashImage,
  MAX_IMAGE_BYTES,
  parseOffset,
  placed,
  problemsOf,
  refusalOf,
  suggestedOffset,
} from "./images";

function image(name: string, offset: string, size = 0x2000): FlashImage {
  return { id: name, name, bytes: new Uint8Array(size), offset };
}

describe("suggestedOffset", () => {
  it("places an ESP32 export by its file names", () => {
    const board = "esp32:esp32:esp32";
    expect(suggestedOffset("weather.ino.bin", board)).toBe("0x10000");
    expect(suggestedOffset("weather.ino.bootloader.bin", board)).toBe("0x1000");
    expect(suggestedOffset("weather.ino.partitions.bin", board)).toBe("0x8000");
    expect(suggestedOffset("boot_app0.bin", board)).toBe("0xe000");
    expect(suggestedOffset("weather.ino.merged.bin", board)).toBe("0x0");
  });

  it("starts the bootloader where the board's chip does", () => {
    expect(suggestedOffset("bootloader.bin", "esp32:esp32:esp32s3")).toBe("0x0");
    expect(suggestedOffset("bootloader.bin", "esp32-c3-devkitm-1")).toBe("0x0");
    expect(suggestedOffset("bootloader.bin", "esp32:esp32:esp32c5")).toBe("0x2000");
    expect(suggestedOffset("bootloader.bin", "esp32:esp32:esp32s2")).toBe("0x1000");
  });

  it("starts an ESP8266 sketch at the flash's first byte", () => {
    expect(suggestedOffset("blink.ino.bin", "esp8266:esp8266:nodemcuv2")).toBe("0x0");
  });
});

describe("parseOffset", () => {
  it("reads hex and decimal, as esptool does", () => {
    expect(parseOffset("0x10000")).toBe(0x10000);
    expect(parseOffset(" 0X1000 ")).toBe(0x1000);
    expect(parseOffset("65536")).toBe(0x10000);
    expect(parseOffset("0")).toBe(0);
  });

  it("refuses what isn't the start of a sector", () => {
    for (const text of ["", "0x", "0x1001", "100", "-4096", "1e4", "0x100000000", "zz"]) {
      expect(parseOffset(text), text).toBeNull();
    }
  });
});

describe("problemsOf", () => {
  it("finds nothing wrong with binaries side by side", () => {
    const images = [image("boot.bin", "0x1000", 0x7000), image("app.bin", "0x10000")];
    expect(problemsOf(images).size).toBe(0);
    expect(placed(images)?.map((item) => item.address)).toEqual([0x1000, 0x10000]);
  });

  it("names the first problem of each binary", () => {
    const problems = problemsOf([
      image("empty.bin", "0x0", 0),
      image("huge.bin", "0x0", MAX_IMAGE_BYTES + 1),
      image("odd.bin", "0x1234"),
      image("app.bin", "0x10000", 0x1001),
      image("data.bin", "0x11000"),
    ]);
    expect(Object.fromEntries(problems)).toEqual({
      "empty.bin": { kind: "empty" },
      "huge.bin": { kind: "too_large" },
      "odd.bin": { kind: "offset" },
      // app.bin's last byte is in the sector data.bin starts, which its erase would wipe.
      "data.bin": { kind: "overlap", other: "app.bin" },
    });
  });

  it("places nothing while a binary has a problem", () => {
    expect(placed([image("app.bin", "nowhere")])).toBeNull();
  });

  it("sorts what it places by address", () => {
    const images = [image("app.bin", "0x10000"), image("boot.bin", "0x1000")];
    expect(placed(images)?.map((item) => item.name)).toEqual(["boot.bin", "app.bin"]);
  });
});

describe("refusalOf", () => {
  const esp32 = { bootloaderOffset: 0x1000, flashBytes: 4 * 1024 * 1024 };
  const at = (name: string, address: number, size = 0x2000) => ({
    name,
    address,
    bytes: new Uint8Array(size),
  });

  it("lets through what fits the chip", () => {
    expect(refusalOf([at("bootloader.bin", 0x1000), at("app.bin", 0x10000)], esp32)).toBeNull();
  });

  it("refuses a bootloader away from where the chip starts", () => {
    expect(refusalOf([at("sketch.bootloader.bin", 0)], esp32)).toEqual({
      kind: "bootloader",
      name: "sketch.bootloader.bin",
      address: 0,
      expected: 0x1000,
    });
  });

  it("refuses a binary past the end of the flash, when its size is known", () => {
    const big = at("app.bin", 0x3ff000, 0x2000);
    expect(refusalOf([big], esp32)).toEqual({
      kind: "fit",
      name: "app.bin",
      flashBytes: 4 * 1024 * 1024,
    });
    expect(refusalOf([big], { ...esp32, flashBytes: null })).toBeNull();
  });
});

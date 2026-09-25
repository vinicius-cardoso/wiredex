import { describe, expect, it } from "vitest";
import { formatSize } from "./sizes";

describe("formatSize", () => {
  it("shows bytes whole, without a decimal", () => {
    expect(formatSize(0, "en")).toBe("0 B");
    expect(formatSize(840, "en")).toBe("840 B");
    expect(formatSize(1023, "en")).toBe("1,023 B");
  });

  it("shows kilobytes and megabytes with one decimal", () => {
    expect(formatSize(1024, "en")).toBe("1.0 KB");
    expect(formatSize(1_258_291, "en")).toBe("1.2 MB");
    expect(formatSize(25 * 1024 * 1024, "en")).toBe("25.0 MB");
  });

  it("climbs to gigabytes and stops there", () => {
    expect(formatSize(5 * 1024 * 1024 * 1024, "en")).toBe("5.0 GB");
  });

  it("localizes the number's decimal mark", () => {
    expect(formatSize(1_258_291, "pt-BR")).toBe("1,2 MB");
  });

  it("shows a plain zero for a nonsense count rather than NaN", () => {
    expect(formatSize(-1, "en")).toBe("0 B");
    expect(formatSize(Number.NaN, "en")).toBe("0 B");
  });
});

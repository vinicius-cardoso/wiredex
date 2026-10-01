import { describe, expect, it } from "vitest";
import { HIGHLIGHT_LIMITS, highlightable, languageOf } from "./languages";

describe("languageOf", () => {
  it.each([
    ["weather_station.ino", "cpp"],
    ["src/sensor.c", "cpp"],
    ["src/sensor.cc", "cpp"],
    ["src/sensor.cpp", "cpp"],
    ["src/sensor.cxx", "cpp"],
    ["include/sensor.h", "cpp"],
    ["include/sensor.hh", "cpp"],
    ["include/sensor.hpp", "cpp"],
    ["include/sensor.hxx", "cpp"],
    ["main.py", "python"],
    ["data/calibration.json", "json"],
  ])("reads %s as %s", (path, language) => {
    expect(languageOf(path)).toBe(language);
  });

  it("compares extensions ignoring case", () => {
    expect(languageOf("Blink.INO")).toBe("cpp");
    expect(languageOf("lib/Sensor.Hpp")).toBe("cpp");
    expect(languageOf("BOOT.PY")).toBe("python");
    expect(languageOf("Config.JSON")).toBe("json");
  });

  it.each([
    "platformio.ini",
    "CMakeLists.txt",
    "README.md",
    "Makefile",
    "sketch.ino.bak",
    "notes.",
    "lib.h/readme",
    "notes.constructor",
  ])("reads %s as plain text", (path) => {
    expect(languageOf(path)).toBe("plain");
  });
});

describe("highlightable", () => {
  it("highlights a file of up to 5,000 lines and 256 KB", () => {
    expect(HIGHLIGHT_LIMITS).toEqual({ lines: 5_000, bytes: 262_144 });
    expect(highlightable({ lines: 0, size: 0 })).toBe(true);
    expect(highlightable({ lines: 5_000, size: 262_144 })).toBe(true);
  });

  it("shows a file past either limit plain", () => {
    expect(highlightable({ lines: 5_001, size: 40_000 })).toBe(false);
    expect(highlightable({ lines: 120, size: 262_145 })).toBe(false);
  });
});

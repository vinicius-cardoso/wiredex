import { describe, expect, it } from "vitest";
import { formatSi, parseSi } from "./notation";

describe("parseSi", () => {
  it.each([
    ["4700", 4700],
    ["4.7e3", 4700],
    ["-40", -40],
    ["4k7", 4700],
    ["2u2", 0.0000022],
    ["1R5", 1.5],
    ["-4k7", -4700],
    ["10k", 10000],
    ["100n", 1e-7],
    ["2.2µ", 0.0000022],
    ["2.2μ", 0.0000022], // The Greek mu a phone types, folded to the micro sign.
    [" 10k ", 10000],
  ])("reads %s as %d", (text, expected) => {
    expect(parseSi(text)).toBeCloseTo(expected, 12);
  });

  it("reads both spellings of a magnitude the same way", () => {
    expect(parseSi("10k")).toBe(parseSi("10000"));
  });

  it.each(["", "10K", "abc", "4k7k", "k", "1.2.3"])("refuses %s", (text) => {
    expect(parseSi(text)).toBeNull();
  });

  it("drops a trailing unit that is the attribute's own", () => {
    expect(parseSi("100nF", "F")).toBe(1e-7);
    expect(parseSi("10kΩ", "Ω")).toBe(10000);
  });

  it("refuses a trailing unit that isn't", () => {
    expect(parseSi("100nH", "F")).toBeNull();
    expect(parseSi("F", "F")).toBeNull();
  });
});

describe("formatSi", () => {
  it.each([
    [4700, "4.7k"],
    [1e-7, "100n"],
    [0.0000022, "2.2µ"],
    [1.5, "1.5"],
    [-40, "-40"],
    [0, "0"],
    [999.99, "1k"], // Rounding to four digits before picking the prefix.
    [1e15, "1000T"], // Past tera the mantissa grows; no prefix is invented.
    [0.1234567, "123.5m"],
  ])("writes %d as %s", (value, expected) => {
    expect(formatSi(value)).toBe(expected);
  });

  it("appends the unit when there is one", () => {
    expect(formatSi(4700, "Ω")).toBe("4.7kΩ");
  });

  it("round trips what it prints", () => {
    for (const value of [4700, 1e-7, 1.5, -40, 0.0000022]) {
      expect(parseSi(formatSi(value))).toBeCloseTo(value, 12);
    }
  });
});

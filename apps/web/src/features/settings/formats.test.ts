import { describe, expect, it } from "vitest";
import { formatsOf } from "./formats";

const AFTERNOON = new Date(2026, 9, 11, 14, 5);

describe("formats", () => {
  it("follows the language until told otherwise", () => {
    expect(formatsOf("en").date(AFTERNOON)).toBe("Oct 11, 2026");
    expect(formatsOf("pt-BR").number(1234.5)).toBe("1.234,5");
    expect(formatsOf("en").number(1234.5)).toBe("1,234.5");
  });

  it.each([
    ["iso", "2026-10-11", "2026-10-11 14:05"],
    ["dmy", "11/10/2026", "11/10/2026 14:05"],
    ["mdy", "10/11/2026", "10/11/2026 14:05"],
  ] as const)("writes %s dates the same in every language", (format, day, dayAndTime) => {
    for (const language of ["en", "pt-BR"]) {
      expect(formatsOf(language, format).date(AFTERNOON)).toBe(day);
      expect(formatsOf(language, format).dateTime(AFTERNOON)).toBe(dayAndTime);
    }
  });

  it("writes numbers with a point or a comma whatever the language", () => {
    expect(formatsOf("pt-BR", "language", "point").number(1234.5)).toBe("1,234.5");
    expect(formatsOf("en", "language", "comma").number(1234.5)).toBe("1.234,5");
    expect(formatsOf("en", "language", "comma").numberLocale).toBe("pt-BR");
  });

  it("reads a date the API sends as text", () => {
    expect(formatsOf("en", "iso").date(AFTERNOON.toISOString())).toBe("2026-10-11");
  });
});

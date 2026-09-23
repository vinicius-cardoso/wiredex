import { describe, expect, it } from "vitest";
import { isThemePreference, resolveTheme } from "./theme";

describe("resolveTheme", () => {
  it.each([
    ["light", false, "light"],
    ["light", true, "light"],
    ["dark", false, "dark"],
    ["system", false, "light"],
    ["system", true, "dark"],
  ] as const)("%s with a dark OS = %s resolves to %s", (preference, systemDark, expected) => {
    expect(resolveTheme(preference, systemDark)).toBe(expected);
  });
});

describe("isThemePreference", () => {
  it("rejects anything that is not light, dark or system", () => {
    expect(isThemePreference("system")).toBe(true);
    expect(isThemePreference("sepia")).toBe(false);
    expect(isThemePreference(null)).toBe(false);
  });
});

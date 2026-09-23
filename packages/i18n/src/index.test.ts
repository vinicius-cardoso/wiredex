import { describe, expect, it } from "vitest";
import { isLanguage, matchLanguage } from "./index";
import en from "./locales/en.json" with { type: "json" };
import ptBR from "./locales/pt-BR.json" with { type: "json" };

function keysOf(messages: object, prefix = ""): string[] {
  return Object.entries(messages).flatMap(([key, value]) =>
    typeof value === "object" && value !== null
      ? keysOf(value, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("catalogs", () => {
  it("translate exactly the same keys", () => {
    expect(keysOf(ptBR).sort()).toEqual(keysOf(en).sort());
  });

  it("have no empty messages", () => {
    const empty = [en, ptBR].flatMap((catalog) =>
      keysOf(catalog).filter((key) => {
        const value = key.split(".").reduce<unknown>((node, part) => {
          return (node as Record<string, unknown>)[part];
        }, catalog);
        return value === "";
      }),
    );
    expect(empty).toEqual([]);
  });
});

describe("matchLanguage", () => {
  it.each([
    [["pt-BR"], "pt-BR"],
    [["pt-PT", "en"], "pt-BR"],
    [["en-US"], "en"],
    [["de-DE", "pt"], "pt-BR"],
    [["de-DE"], "en"],
    [[], "en"],
  ])("maps %j to %s", (preferred, expected) => {
    expect(matchLanguage(preferred)).toBe(expected);
  });
});

describe("isLanguage", () => {
  it("accepts only supported language tags", () => {
    expect(isLanguage("pt-BR")).toBe(true);
    expect(isLanguage("pt")).toBe(false);
    expect(isLanguage(undefined)).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { safeRedirect } from "./redirect";

describe("safeRedirect", () => {
  it("keeps paths on this site", () => {
    expect(safeRedirect("/sessions?tab=all")).toBe("/sessions?tab=all");
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "sessions", 42, undefined])(
    "drops %s",
    (value) => {
      expect(safeRedirect(value)).toBeUndefined();
    },
  );
});

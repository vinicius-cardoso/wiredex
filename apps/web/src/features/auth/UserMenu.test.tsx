import { describe, expect, it } from "vitest";
import { initials } from "./UserMenu";

describe("initials", () => {
  it("takes the first letter of the first and the last word", () => {
    expect(initials("Vinícius Cardoso")).toBe("VC");
    expect(initials("Ada King Lovelace")).toBe("AL");
  });

  it("takes one letter of a single word", () => {
    expect(initials("Vinicius")).toBe("V");
  });

  it("ignores spaces around and between, and upper-cases", () => {
    expect(initials("  ada   lovelace ")).toBe("AL");
  });
});

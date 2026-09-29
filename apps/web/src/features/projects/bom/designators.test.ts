import { describe, expect, it } from "vitest";
import { readDesignators } from "./designators";

/** The server's own examples (tests/projects/test_designators.py), read by the mirror. */
describe("readDesignators", () => {
  it.each([
    ["r01", "R1"],
    ["Ｒ１", "R1"],
    [" c12 ", "C12"],
    ["ABCDEFGH9999", "ABCDEFGH9999"],
  ])("reads %j as %s", (typed, text) => {
    expect(readDesignators(typed)).toMatchObject({ text, count: 1, problem: null });
  });

  it.each(["U1A", "U1.2", "R0", "R10000", "ABCDEFGHI1", "1R", "Ω1"])(
    "refuses %j, naming it",
    (typed) => {
      expect(readDesignators(typed).problem).toEqual({ code: "invalid_designator", item: typed });
    },
  );

  it.each(["R1-4", "R1 – R4", "R1—R4", "r1-r4", "R1,R2 R3\tR4", "R4, R3, R2, R1"])(
    "reads %j as R1–R4",
    (typed) => {
      expect(readDesignators(typed)).toMatchObject({ text: "R1–R4", count: 4, problem: null });
    },
  );

  it.each(["R4-R1", "R3-R3", "R1-C4"])("refuses the range %j", (typed) => {
    expect(readDesignators(typed).problem).toEqual({ code: "invalid_range", item: typed });
  });

  it.each(["R1-0", "R1-R", "R1--R3", "-R1"])("refuses %j as not a designator", (typed) => {
    expect(readDesignators(typed).problem).toEqual({ code: "invalid_designator", item: typed });
  });

  it.each([
    ["R1, R1", "R1"],
    ["R1-R3, R2", "R2"],
    ["R2, R1-R3", "R2"],
  ])("refuses %j, naming the repeat %s", (typed, item) => {
    expect(readDesignators(typed).problem).toEqual({ code: "repeated_designator", item });
  });

  it("takes 256 designators and refuses 257", () => {
    expect(readDesignators("R1-256").count).toBe(256);
    expect(readDesignators("R1-256, C1").problem).toEqual({
      code: "too_many_designators",
      item: null,
    });
    expect(readDesignators("R1–R9999").problem?.code).toBe("too_many_designators");
  });

  it.each([
    ["R7, r1-3, C1", "C1, R1–R3, R7"],
    ["R2, R1", "R1, R2"],
    ["R1 R2 R4 R5 R6", "R1, R2, R4–R6"],
    ["R9, R10, R11, RN1", "R9–R11, RN1"],
  ])("writes %j back as %s", (typed, text) => {
    expect(readDesignators(typed).text).toBe(text);
  });

  it("reads its own canonical text back as the same designators", () => {
    const first = readDesignators("C3, r1-3, R7, U1, C1, C2, R9-11");
    const again = readDesignators(first.text ?? "");

    expect(again.designators).toEqual(first.designators);
    expect(again.text).toBe(first.text);
  });

  it("reads blank text as no designators", () => {
    expect(readDesignators("  , ")).toEqual({
      designators: [],
      text: "",
      count: 0,
      problem: null,
    });
  });
});

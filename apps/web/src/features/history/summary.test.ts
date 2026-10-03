import { describe, expect, it } from "vitest";
import { aChange, aRowChange } from "../../test/server";
import { isLongValue, summarize } from "./summary";

describe("summarize", () => {
  it("names the one field a record's own row changed", () => {
    const summary = summarize(aChange());

    expect(summary).toMatchObject({
      type: "field",
      own: true,
      field: { name: "mpn", before: "RC0805FR-074K7", after: "RC0805FR-074K7L" },
    });
  });

  it("counts the fields when one row changed several", () => {
    const change = aChange({
      rows: [
        aRowChange({
          fields: [
            { name: "name", before: "A", after: "B" },
            { name: "notes", before: null, after: "kept dry" },
          ],
        }),
      ],
    });

    expect(summarize(change)).toMatchObject({ type: "fields", own: true });
  });

  it("marks a change to what the record holds as made to that row", () => {
    const change = aChange({
      record: { kind: "firmware", id: "0199aaaa-0000-7000-8000-0000000000f9", label: "Weather" },
      rows: [
        aRowChange({
          kind: "version",
          label: "0.1.0",
          fields: [{ name: "changelog", before: null, after: "First" }],
        }),
      ],
    });

    expect(summarize(change)).toMatchObject({ type: "field", own: false });
  });

  it("names the one row a change added or removed", () => {
    const added = aRowChange({ kind: "source_file", operation: "insert", label: "main.cpp" });

    expect(summarize(aChange({ rows: [added] }))).toEqual({ type: "row", row: added });
  });

  it("counts every row a change wrote, those past the first twenty too", () => {
    const pin = aRowChange({ kind: "pin", operation: "insert", label: "1 VCC" });

    expect(summarize(aChange({ rows: [pin], more_rows: 4 }))).toEqual({
      type: "rows",
      count: 5,
      rows: [pin],
    });
  });

  it("says nothing else changed when a move to the trash only moved it", () => {
    const moved = aChange({
      action: "moved_to_trash",
      rows: [
        aRowChange({ fields: [{ name: "trashed_at", before: null, after: "2026-10-01T18:02" }] }),
      ],
    });

    expect(summarize(moved)).toEqual({ type: "nothing" });
  });

  it("keeps a trash field that isn't the trash move itself", () => {
    const edited = aChange({
      rows: [aRowChange({ fields: [{ name: "trashed_at", before: "x", after: null }] })],
    });

    expect(summarize(edited)).toMatchObject({ type: "field", field: { name: "trashed_at" } });
  });

  it("says nothing changed for a change without rows", () => {
    expect(summarize(aChange({ rows: [], more_rows: 0 }))).toEqual({ type: "nothing" });
  });
});

describe("isLongValue", () => {
  it("boxes a value past 120 characters or with a line break", () => {
    expect(isLongValue("x".repeat(120))).toBe(false);
    expect(isLongValue("x".repeat(121))).toBe(true);
    expect(isLongValue("void setup() {\n}")).toBe(true);
  });
});

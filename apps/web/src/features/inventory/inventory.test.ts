import { describe, expect, it } from "vitest";
import { aLocation } from "../../test/server";
import { locationPath, matchesLocation } from "./inventory";

const lab = aLocation({ name: "Lab", code: "WX-L-0001" });
const cabinet = aLocation({
  id: "0199ffff-0000-7000-8000-000000000002",
  parent_id: lab.id,
  name: "Armário A",
  code: "WX-L-0002",
});
const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  parent_id: cabinet.id,
  name: "Drawer 3",
  code: "WX-L-0003",
});

describe("locationPath", () => {
  it("names every location from the root down", () => {
    expect(locationPath(drawer, [lab, cabinet, drawer])).toBe("Lab / Armário A / Drawer 3");
    expect(locationPath(lab, [lab, cabinet, drawer])).toBe("Lab");
  });

  it("ends where a parent is missing from the list", () => {
    expect(locationPath(drawer, [drawer])).toBe("Drawer 3");
  });

  it("stops at a loop in the parents", () => {
    const one = aLocation({ id: "a", parent_id: "b", name: "One" });
    const two = aLocation({ id: "b", parent_id: "a", name: "Two" });

    expect(locationPath(one, [one, two])).toBe("Two / One");
  });
});

describe("matchesLocation", () => {
  it("finds the text in the name or the code, ignoring case and accents", () => {
    expect(matchesLocation(cabinet, "armario")).toBe(true);
    expect(matchesLocation(cabinet, "wx-l-0002")).toBe(true);
    expect(matchesLocation(cabinet, "drawer")).toBe(false);
  });

  it("finds the text in the path only when one is given", () => {
    const path = locationPath(drawer, [lab, cabinet, drawer]);

    expect(matchesLocation(drawer, "lab")).toBe(false);
    expect(matchesLocation(drawer, "lab", path)).toBe(true);
    expect(matchesLocation(drawer, "  ARMÁRIO a/dRa ", path)).toBe(true);
    expect(matchesLocation(drawer, "lab / drawer", path)).toBe(false);
  });

  it("takes blank text as matching every location", () => {
    expect(matchesLocation(drawer, "   ")).toBe(true);
  });
});

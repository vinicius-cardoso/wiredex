import { describe, expect, it } from "vitest";
import {
  MISSIONS,
  missionsDone,
  NO_MEMORY,
  PAGE_ANCHORS,
  PAGE_TOURS,
  readMemory,
  tourPageAt,
  writeMemory,
} from "./tour";

const NOTHING = { parts: 0, boards: 0, projects: 0, firmware: 0, locations: 0, categories: 0 };

describe("missionsDone", () => {
  it("ticks a mission once the bench holds one of its record", () => {
    expect([...missionsDone({ ...NOTHING, locations: 2, firmware: 1 }, [])]).toEqual([
      "location",
      "firmware",
    ]);
  });

  it("ticks the palette's by what was done here, and nothing before the bench is counted", () => {
    expect([...missionsDone(undefined, ["palette"])]).toEqual(["palette"]);
    expect(missionsDone(undefined, []).size).toBe(0);
  });

  it("ticks them all on a full bench", () => {
    const full = { parts: 1, boards: 1, projects: 1, firmware: 1, locations: 1, categories: 1 };
    expect(missionsDone(full, ["palette"]).size).toBe(MISSIONS.length);
  });
});

describe("the tour's memory", () => {
  it("reads back what was written", () => {
    writeMemory({ offered: true, missions: true, marked: ["palette"] });
    expect(readMemory()).toEqual({ offered: true, missions: true, marked: ["palette"] });
  });

  it.each([
    ["nothing stored", null],
    ["something that isn't JSON", "{oops"],
    ["a value that isn't an object", "7"],
  ])("remembers nothing from %s", (_, stored) => {
    if (stored === null) localStorage.removeItem("wiredex.tour");
    else localStorage.setItem("wiredex.tour", stored);
    expect(readMemory()).toEqual(NO_MEMORY);
  });

  it("keeps only what has the right shape", () => {
    localStorage.setItem("wiredex.tour", JSON.stringify({ offered: "yes", marked: ["a", 3] }));
    expect(readMemory()).toEqual({ offered: false, missions: false, marked: ["a"] });
  });
});

describe("the pages with a tour of their own", () => {
  it("are found by their address, a trailing slash aside", () => {
    expect(tourPageAt("/parts")).toBe("parts");
    expect(tourPageAt("/units/")).toBe("units");
    expect(tourPageAt("/")).toBeNull();
    expect(tourPageAt("/parts/new")).toBeNull();
    expect(tourPageAt("/projects/0199aaaa")).toBeNull();
  });

  it("each point at anchors the pages carry, and at least two of them", () => {
    for (const tour of Object.values(PAGE_TOURS)) {
      expect(tour.stops.length).toBeGreaterThanOrEqual(2);
      for (const anchor of tour.stops) expect(PAGE_ANCHORS[anchor]).toMatch(/^\[data-tour="/);
    }
  });
});

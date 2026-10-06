import { describe, expect, it } from "vitest";
import { MISSIONS, missionsDone, NO_MEMORY, readMemory, writeMemory } from "./tour";

const NOTHING = { parts: 0, boards: 0, projects: 0, firmware: 0, locations: 0 };

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
    const full = { parts: 1, boards: 1, projects: 1, firmware: 1, locations: 1 };
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

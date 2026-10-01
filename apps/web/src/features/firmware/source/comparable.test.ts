import type { VersionSummary } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { V100, V110, V120, v100, v110, v120 } from "../../../test/firmware";
import { aVersion, versionSummaryOf } from "../../../test/server";
import { comparisonBase, validateCompareSearch } from "./comparable";

const V200 = "0199ffff-0000-7000-8000-0000000000a4";

describe("comparisonBase", () => {
  it("offers a version's base before the next version down, and none below the first", () => {
    // A rewrite started from 1.0.0 compares with it, not with 1.2.0 below it.
    const rewrite = aVersion({
      id: V200,
      version: "2.0.0",
      based_on: { id: V100, version: "1.0.0" },
    });
    const versions = [rewrite, v120, v110, v100].map(versionSummaryOf);

    expect(comparisonBase(versions, V200)).toBe(V100);
    expect(comparisonBase(versions, V120)).toBe(V110);
    expect(comparisonBase(versions, V100)).toBeNull();
  });

  it("offers the next version down when the base isn't listed, and none for a stranger", () => {
    // 1.2.0 started empty, or from a version since deleted, which 13 clears; 1.1.0's base
    // gone from a list loaded before.
    const versions = [
      versionSummaryOf(aVersion({ id: V120, version: "1.2.0" })),
      { ...versionSummaryOf(v110), based_on: "0199ffff-0000-7000-8000-0000000000ff" },
      versionSummaryOf(v100),
    ];

    expect(comparisonBase(versions, V120)).toBe(V110);
    expect(comparisonBase(versions, V110)).toBe(V100);
    expect(comparisonBase(versions, "0199ffff-0000-7000-8000-0000000000fe")).toBeNull();
  });
});

/** Mulberry32: the same cases on every run, so a failing case fails again. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4_294_967_296;
  };
}

/**
 * One to six versions, highest first, each based on none, on another of them, on one the list
 * doesn't hold, or on itself. 13 never records the last, a version being started from one that
 * already exists; it is here so "never the version itself" is checked rather than assumed.
 */
function versionsOf(random: () => number): VersionSummary[] {
  const ids = Array.from({ length: 1 + Math.floor(random() * 6) }, (_, at) => `version-${at}`);
  return ids.map((id, at) => {
    const choice = random();
    const other = ids[Math.floor(random() * ids.length)] ?? null;
    const basedOn = choice < 0.25 ? null : choice < 0.35 ? "elsewhere" : choice < 0.45 ? id : other;
    return {
      ...versionSummaryOf(aVersion()),
      id,
      version: `${ids.length - at}.0.0`,
      based_on: basedOn,
    };
  });
}

/**
 * Property 5: the default base is another version of the firmware. For any list of versions
 * and any version in it, `comparisonBase` answers the base when the list holds it, else the next
 * version down the list, else none, and never the version itself.
 *
 * **Validates: Requirements 4.6**
 */
describe("property 5: the default base is another version of the firmware", () => {
  const random = seeded(5);
  const cases = Array.from({ length: 200 }, () => {
    const versions = versionsOf(random);
    return { versions, at: Math.floor(random() * versions.length) };
  });

  it("answers the listed base, else the next version down, else none, never the version", () => {
    for (const { versions, at } of cases) {
      const version = versions[at];
      const sample = JSON.stringify({
        versions: versions.map(({ id, based_on }) => ({ id, based_on })),
        at,
      });
      expect(version, sample).toBeDefined();
      if (!version) continue;
      const base = version.based_on;
      const listed = base !== version.id && versions.some((other) => other.id === base);
      const expected = listed ? base : (versions[at + 1]?.id ?? null);

      const answer = comparisonBase(versions, version.id);

      expect(answer, sample).toBe(expected);
      expect(answer, sample).not.toBe(version.id);
    }
  });
});

describe("validateCompareSearch", () => {
  it("keeps two versions or none, so the selects always have both sides", () => {
    expect(validateCompareSearch({ from: V100, to: V110 })).toEqual({ from: V100, to: V110 });
    // The same version twice, and one the firmware may not list, are the page's to say.
    expect(validateCompareSearch({ from: V110, to: V110 })).toEqual({ from: V110, to: V110 });
    expect(validateCompareSearch({ from: V100 })).toEqual({});
    expect(validateCompareSearch({ from: "", to: V110 })).toEqual({});
    expect(validateCompareSearch({ from: 100, to: V110 })).toEqual({});
    expect(validateCompareSearch({})).toEqual({});
  });
});

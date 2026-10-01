import type { VersionSummary } from "@wiredex/api-client";

/** The two versions a comparison's address names, both or neither (decision 9). */
export type CompareSearch = { from?: string; to?: string };

/**
 * The comparison's address, parsed: two ids or none, so the selects always have both sides to
 * show. An id that isn't the firmware's is kept for the page to say so (requirement 4.8);
 * without the pair the page opens the highest version against its base.
 */
export function validateCompareSearch(raw: Record<string, unknown>): CompareSearch {
  const { from, to } = raw;
  return typeof from === "string" && from !== "" && typeof to === "string" && to !== ""
    ? { from, to }
    : {};
}

/**
 * Decision 9's default From for the version VERSION_ID: its base when the firmware lists it,
 * else the next version down VERSIONS, which 13 answers highest first, else none. Never the
 * version itself (property 5), and none for a version the firmware doesn't list.
 */
export function comparisonBase(versions: VersionSummary[], versionId: string): string | null {
  const at = versions.findIndex((version) => version.id === versionId);
  if (at === -1) return null;
  const baseId = versions[at]?.based_on;
  const base = versions.find((version) => version.id === baseId && version.id !== versionId);
  return (base ?? versions[at + 1])?.id ?? null;
}

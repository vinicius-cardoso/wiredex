import type { VersionSummary } from "@wiredex/api-client";

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

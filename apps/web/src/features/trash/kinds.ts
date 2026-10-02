import type { QueryKey } from "@tanstack/react-query";
import type { TrashKind } from "@wiredex/api-client";
import { catalogKeys } from "../catalog/catalog";
import { firmwareKeys } from "../firmware/firmware";
import { inventoryKeys } from "../inventory/inventory";
import { pinUsageKeys } from "../projects/netlist/pinUsage";
import { projectKeys } from "../projects/projects";

/** The four kinds, in the order the API names them. */
export const TRASH_KINDS: readonly TrashKind[] = ["part", "unit", "project", "firmware"];

/** Each kind's word, as the trash lists it. */
export function kindKey(kind: TrashKind) {
  return `trash.kind.${kind}` as const;
}

/**
 * The caches a record of the kind shows up in, which its restore or its delete for good makes
 * stale (requirement 9.7). A part is the catalog's, and names its stock; a unit is inventory's,
 * and a firmware's board; a project's revisions are what firmware runs on and what parts' pins
 * are wired to; a firmware is firmware's alone. A function, read when a write lands, so this
 * module never reads another's keys while the modules are still loading.
 */
export function cachesOf(kind: TrashKind): QueryKey[] {
  switch (kind) {
    case "part":
      return [catalogKeys.all, inventoryKeys.all];
    case "unit":
      return [inventoryKeys.all, firmwareKeys.all];
    case "project":
      return [projectKeys.all, firmwareKeys.all, pinUsageKeys.all];
    case "firmware":
      return [firmwareKeys.all];
  }
}

import type { RevisionStatus } from "@wiredex/api-client";

/** Each status's i18n key, so every screen names a status the same way. */
export function statusKey(status: RevisionStatus) {
  return `projects.status.${status}` as const;
}

/**
 * Each status's colour, from the theme tokens: a draft and a dismantled build are quiet, a
 * reserved one takes the accent, a built one reads as done.
 */
export const statusTone: Record<RevisionStatus, string> = {
  draft: "text-muted",
  reserved: "text-accent-ink",
  built: "text-ok",
  dismantled: "text-muted",
};

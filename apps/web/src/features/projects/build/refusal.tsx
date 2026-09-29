import type { TFunction } from "i18next";
import type { LifecycleRefusal } from "./lifecycle";

/**
 * A refusal in the reader's language, from the code the API answers (requirement 13.13). The
 * per-code sentences take the unit's code, the status and the transition where they help; a
 * `short` says the report follows, which the dialog shows. A refusal with no code, a 404 or
 * FastAPI's own 422, gets the generic message. The API's English sentence is never shown.
 */
export function refusalMessage(t: TFunction, refusal: LifecycleRefusal | null): string {
  if (!refusal?.code) return t("projects.lifecycle.refusal.generic");
  const status = refusal.revisionStatus ? t(`projects.status.${refusal.revisionStatus}`) : "";
  const transition = refusal.transition
    ? t(`projects.lifecycle.transition.${refusal.transition}`)
    : "";
  return String(
    t(`projects.lifecycle.refusal.${refusal.code}`, {
      unit: refusal.unitCode ?? "",
      status,
      transition,
    }),
  );
}

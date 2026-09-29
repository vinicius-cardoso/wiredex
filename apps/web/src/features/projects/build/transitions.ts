import type { RevisionStatus, Transition } from "@wiredex/api-client";

/**
 * How the web offers a transition: its label key, and how it is confirmed — a `dialog` that
 * gathers a choice (reserve's units, dismantle's location), or an in-place `confirm` for a
 * build or a cancel that takes nothing. The API still decides: a stale screen offering a move
 * the status no longer allows is refused as `transition_not_allowed`, shown like any refusal.
 */
export type TransitionAction = {
  transition: Transition;
  kind: "dialog" | "confirm";
};

/** Each transition's action, keyed by the transition the API names. */
export const TRANSITION_ACTIONS: Record<Transition, TransitionAction> = {
  reserve: { transition: "reserve", kind: "dialog" },
  build: { transition: "build", kind: "confirm" },
  cancel: { transition: "cancel", kind: "confirm" },
  dismantle: { transition: "dismantle", kind: "dialog" },
};

/** A transition's action label key, typed so `t` accepts it (as `statusKey` is). */
export function actionKey(transition: Transition) {
  return `projects.lifecycle.action.${transition}` as const;
}

/** A reserved or built revision holds stock, so it can't be deleted (design's decision 7). */
export function holdsStock(status: RevisionStatus): boolean {
  return status === "reserved" || status === "built";
}

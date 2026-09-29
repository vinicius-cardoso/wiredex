import type { RevisionDetails } from "@wiredex/api-client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { revisionName } from "../projects";
import { ConfirmTransition } from "./ConfirmTransition";
import { DismantleDialog } from "./DismantleDialog";
import { useBuildRevision, useCancelReservation, useLifecycle } from "./lifecycle";
import { ReserveDialog } from "./ReserveDialog";
import { actionKey, TRANSITION_ACTIONS } from "./transitions";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type Props = { revision: RevisionDetails };

/**
 * The transitions a revision allows, beside its status: *Reserve parts* for a draft, *Build*
 * and *Cancel reservation* for a reserved revision, *Dismantle* for a built one, and for a
 * dismantled one a line saying a new build starts from a fork (requirements 1.6, 13.1). The
 * transitions come from the lifecycle read, so a status change refreshes them in place; the
 * status shown is the revision's own, kept current by the same refresh (requirement 13.7).
 *
 * A build and a cancel confirm in place (`ConfirmTransition`); a reserve and a dismantle open a
 * dialog. Every control is a button with an accessible name, and each confirmation and dialog
 * works by keyboard alone (requirement 13.15).
 */
export function LifecycleActions({ revision }: Props) {
  const { t } = useTranslation();
  const lifecycle = useLifecycle(revision.id);
  const [open, setOpen] = useState<"reserve" | "dismantle" | null>(null);
  const [confirming, setConfirming] = useState<"build" | "cancel" | null>(null);

  const transitions = lifecycle.data?.transitions ?? [];

  if (revision.status === "dismantled") {
    return <p className="text-sm text-muted">{t("projects.lifecycle.dismantledNote")}</p>;
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-start gap-2">
        {transitions.map((transition) => {
          const spec = TRANSITION_ACTIONS[transition];
          return (
            <button
              key={transition}
              type="button"
              onClick={() => {
                if (spec.kind === "dialog") setOpen(transition as "reserve" | "dismantle");
                else setConfirming(transition as "build" | "cancel");
              }}
              className={action}
            >
              {t(actionKey(transition))}
            </button>
          );
        })}
      </div>

      {confirming === "build" && (
        <BuildConfirm revision={revision} onDone={() => setConfirming(null)} />
      )}
      {confirming === "cancel" && (
        <CancelConfirm revision={revision} onDone={() => setConfirming(null)} />
      )}

      {open === "reserve" && (
        <ReserveDialog revisionId={revision.id} onClose={() => setOpen(null)} />
      )}
      {open === "dismantle" && (
        <DismantleDialog revisionId={revision.id} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

function BuildConfirm({ revision, onDone }: { revision: RevisionDetails; onDone: () => void }) {
  const { t } = useTranslation();
  const build = useBuildRevision();
  return (
    <ConfirmTransition
      question={t("projects.lifecycle.build.question", { name: revisionName(t, revision) })}
      confirmLabel={t("projects.lifecycle.build.confirm")}
      pending={build.isPending}
      error={build.error}
      onConfirm={() => build.mutate(revision.id, { onSuccess: onDone })}
      onCancel={onDone}
    />
  );
}

function CancelConfirm({ revision, onDone }: { revision: RevisionDetails; onDone: () => void }) {
  const { t } = useTranslation();
  const cancel = useCancelReservation();
  return (
    <ConfirmTransition
      question={t("projects.lifecycle.cancel.question", { name: revisionName(t, revision) })}
      confirmLabel={t("projects.lifecycle.cancel.confirm")}
      pending={cancel.isPending}
      error={cancel.error}
      onConfirm={() => cancel.mutate(revision.id, { onSuccess: onDone })}
      onCancel={onDone}
    />
  );
}

import type { Net, Netlist, Severity } from "@wiredex/api-client";
import { type KeyboardEvent, type RefObject, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NetRow } from "./NetRow";
import { netCell } from "./netCells";
import {
  bodyOf,
  draftOf,
  FIELD_ORDER,
  type NetDraft,
  type NetErrors,
  NetFields,
  refusalOf,
  useNetFieldRefs,
  withoutChanged,
} from "./netFields";
import { useRemoveNet, useUpdateNet } from "./netlist";

type Props = {
  revisionId: string;
  net: Net;
  netlist: Netlist;
  severities?: ReadonlyMap<string, Severity> | undefined;
};

const action = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

/**
 * A net of a draft's netlist. *Edit net SDA* turns the row into the add row's fields, in
 * place: Enter saves, Escape puts the net back as it was, and either way focus returns to
 * *Edit* (requirement 10.6). *Remove net SDA* asks in the row first, focus on *Keep*, so a
 * stray Enter keeps the net (requirement 10.7).
 */
export function NetEditRow({ revisionId, net, netlist, severities }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"view" | "edit" | "remove">("view");
  const editRef = useRef<HTMLButtonElement>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const [focusOn, setFocusOn] = useState<"edit" | "remove" | "keep" | "name" | null>(null);
  const refs = useNetFieldRefs();

  useEffect(() => {
    if (!focusOn) return;
    const target = { edit: editRef, remove: removeRef, keep: keepRef, name: refs.name }[focusOn];
    target.current?.focus();
    setFocusOn(null);
  }, [focusOn, refs.name]);

  function show(next: typeof mode, focus: NonNullable<typeof focusOn>) {
    setMode(next);
    setFocusOn(focus);
  }

  if (mode === "edit") {
    return (
      <EditingRow
        revisionId={revisionId}
        net={net}
        netlist={netlist}
        refs={refs}
        onDone={() => show("view", "edit")}
      />
    );
  }

  return (
    <NetRow net={net} severities={severities}>
      <td className={netCell}>
        {mode === "view" ? (
          <div className="flex flex-wrap gap-2">
            <button
              ref={editRef}
              type="button"
              aria-label={t("projects.netlist.editor.editNet", { name: net.name })}
              onClick={() => show("edit", "name")}
              className={action}
            >
              {t("projects.netlist.editor.edit")}
            </button>
            <button
              ref={removeRef}
              type="button"
              aria-label={t("projects.netlist.editor.removeNet", { name: net.name })}
              onClick={() => show("remove", "keep")}
              className={`${action} border-crit text-crit`}
            >
              {t("projects.netlist.editor.remove")}
            </button>
          </div>
        ) : (
          <RemoveQuestion
            revisionId={revisionId}
            net={net}
            keepRef={keepRef}
            onKeep={() => show("view", "remove")}
          />
        )}
      </td>
    </NetRow>
  );
}

type EditingProps = Props & { refs: ReturnType<typeof useNetFieldRefs>; onDone: () => void };

function EditingRow({ revisionId, net, netlist, refs, onDone }: EditingProps) {
  const { t } = useTranslation();
  const update = useUpdateNet();
  const [draft, setDraft] = useState<NetDraft>(() => draftOf(net));
  const [errors, setErrors] = useState<NetErrors>({});
  const [rowError, setRowError] = useState<string | null>(null);

  function save() {
    if (update.isPending) return;
    update.mutate(
      { revisionId, netId: net.id, body: bodyOf(draft) },
      {
        onSuccess: onDone,
        onError: (error) => {
          const { fields, row } = refusalOf(t, error, t("projects.netlist.editor.error"));
          setErrors(fields);
          setRowError(row);
          const first = FIELD_ORDER.find((field) => fields[field]);
          if (first) refs[first].current?.focus();
        },
      },
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    // The pin list's own Enter and Escape, while its list is open, are already handled.
    if (event.isDefaultPrevented()) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onDone();
    } else if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      save();
    }
  }

  return (
    <tr
      aria-label={t("projects.netlist.editor.editing", { name: net.name })}
      onKeyDown={onKeyDown}
      className="border-b border-border bg-surface-2"
    >
      <NetFields
        draft={draft}
        onChange={(next) => {
          setErrors(withoutChanged(errors, draft, next));
          setDraft(next);
        }}
        errors={errors}
        refs={refs}
        netlist={netlist}
      />
      <td className={netCell}>
        <div className="grid justify-items-start gap-1">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={save}
              disabled={update.isPending}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {update.isPending
                ? t("projects.netlist.editor.saving")
                : t("projects.netlist.editor.save")}
            </button>
            <button type="button" onClick={onDone} className={action}>
              {t("projects.netlist.editor.cancel")}
            </button>
          </div>
          {rowError && (
            <p role="alert" className="text-sm text-crit">
              {rowError}
            </p>
          )}
        </div>
      </td>
    </tr>
  );
}

type RemoveProps = {
  revisionId: string;
  net: Net;
  keepRef: RefObject<HTMLButtonElement | null>;
  onKeep: () => void;
};

function RemoveQuestion({ revisionId, net, keepRef, onKeep }: RemoveProps) {
  const { t } = useTranslation();
  const remove = useRemoveNet();
  return (
    <div className="grid justify-items-start gap-1">
      <p>{t("projects.netlist.editor.removeQuestionOf", { name: net.name })}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ revisionId, netId: net.id })}
          className={`${action} border-crit text-crit`}
        >
          {t("projects.netlist.editor.removeConfirm")}
        </button>
        <button ref={keepRef} type="button" onClick={onKeep} className={action}>
          {t("projects.netlist.editor.keep")}
        </button>
      </div>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("projects.netlist.editor.removeError")}
        </p>
      )}
    </div>
  );
}

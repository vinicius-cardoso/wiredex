import type { Netlist } from "@wiredex/api-client";
import { type KeyboardEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { netCell } from "./netCells";
import {
  bodyOf,
  emptyNet,
  FIELD_ORDER,
  type NetDraft,
  type NetErrors,
  NetFields,
  refusalOf,
  useNetFieldRefs,
  withoutChanged,
} from "./netFields";
import { useAddNet } from "./netlist";

/**
 * The table's last row, which adds a net (spec 11, requirement 10.3, decision 14): Name, Color,
 * Pins and Notes, and Enter adds from any of them. Once the net is added the row clears and
 * Name takes focus again, so a breadboard goes in net after net from the keyboard. A refusal
 * lands on the field it names, which takes focus (requirement 10.8).
 */
export function NetAddRow({ revisionId, netlist }: { revisionId: string; netlist: Netlist }) {
  const { t } = useTranslation();
  const add = useAddNet();
  const refs = useNetFieldRefs();
  const [draft, setDraft] = useState<NetDraft>(emptyNet);
  const [errors, setErrors] = useState<NetErrors>({});
  const [rowError, setRowError] = useState<string | null>(null);

  function submit() {
    if (add.isPending) return;
    add.mutate(
      { revisionId, body: bodyOf(draft) },
      {
        onSuccess: () => {
          setDraft(emptyNet);
          setErrors({});
          setRowError(null);
          refs.name.current?.focus();
        },
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
    // The pin list's own Enter, picking a suggestion, has already been handled.
    if (event.key !== "Enter" || event.isDefaultPrevented()) return;
    if (!(event.target instanceof HTMLInputElement)) return;
    event.preventDefault();
    submit();
  }

  return (
    <tr aria-label={t("projects.netlist.editor.newNet")} onKeyDown={onKeyDown}>
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
          <button
            type="button"
            onClick={submit}
            disabled={add.isPending}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold whitespace-nowrap text-on-primary hover:opacity-90 disabled:opacity-60"
          >
            {add.isPending ? t("projects.netlist.editor.adding") : t("projects.netlist.editor.add")}
          </button>
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

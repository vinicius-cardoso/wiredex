import { Link } from "@tanstack/react-router";
import type { PinUse } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan, StackedTable } from "../../../shared/ui/block";
import { statusKey } from "../status";
import { netCell } from "./netCells";
import { usePinUsage } from "./pinUsage";
import { WireSwatch } from "./WireSwatch";

type Row = { key: string; number: string; label: string | null; uses: PinUse[] };

/**
 * A part's pin usage, on its page under the pinout (spec 12, requirement 10.5): each pin with its
 * label and the nets on it in every revision of the bench, each linking to its revision's
 * wiring; a free pin says so; the numbers the pinout doesn't hold follow as *other pins*. The
 * filter keeps the pins whose number, label or function contains the text (10.6). A part with no
 * pinout and no references shows nothing. Where its block is narrow each pin becomes a card,
 * so the page never scrolls sideways (10.10).
 */
export function PinUsageSection({
  partId,
  span,
}: {
  partId: string;
  span?: BlockSpan | undefined;
}) {
  const { t } = useTranslation();
  const filterId = useId();
  const [filter, setFilter] = useState("");
  const usage = usePinUsage(partId);

  if (usage.isPending) return null;
  if (usage.isError) {
    return (
      <Block title={t("projects.pinUsage.title")} span={span}>
        <p role="alert" className="text-crit">
          {t("projects.pinUsage.error")}
        </p>
      </Block>
    );
  }
  const { pins, others, has_pinout } = usage.data;
  if (!has_pinout && others.length === 0) return null;

  const text = filter.trim().toLocaleLowerCase();
  const matches = (...fields: (string | null)[]) =>
    !text || fields.some((field) => field?.toLocaleLowerCase().includes(text));
  const pinRows: Row[] = pins
    .filter((pin) => matches(pin.number, pin.label, ...pin.functions))
    .map((pin) => ({ key: pin.number, number: pin.number, label: pin.label, uses: pin.uses }));
  const otherRows: Row[] = others
    .filter((other) => matches(other.pin))
    .map((other) => ({
      key: `other-${other.pin}`,
      number: other.pin,
      label: null,
      uses: other.uses,
    }));

  return (
    <Block title={t("projects.pinUsage.title")} span={span}>
      <div className="grid max-w-sm gap-1">
        <label htmlFor={filterId} className="text-sm font-medium">
          {t("projects.pinUsage.filter")}
        </label>
        <input
          id={filterId}
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder={t("projects.pinUsage.filterPlaceholder")}
          className="rounded-md border border-border-strong bg-surface px-3 py-1.5"
        />
      </div>

      {pinRows.length + otherRows.length === 0 ? (
        <p className="text-sm text-muted">{t("projects.pinUsage.noMatch")}</p>
      ) : (
        <StackedTable below="sm">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("projects.pinUsage.caption")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.pinUsage.columns.pin")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.pinUsage.columns.label")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.pinUsage.columns.nets")}
                </th>
              </tr>
            </thead>
            <tbody>
              {pinRows.map((row) => (
                <PinRow key={row.key} row={row} />
              ))}
            </tbody>
            {otherRows.length > 0 && (
              <tbody>
                <tr className="border-b border-border">
                  <th scope="colgroup" colSpan={3} className={`${netCell} font-semibold`}>
                    {t("projects.pinUsage.others")}
                  </th>
                </tr>
                {otherRows.map((row) => (
                  <PinRow key={row.key} row={row} />
                ))}
              </tbody>
            )}
          </table>
        </StackedTable>
      )}
    </Block>
  );
}

function PinRow({ row }: { row: Row }) {
  const { t, i18n } = useTranslation();
  return (
    <tr className="border-b border-border align-top">
      <th scope="row" className={`${netCell} font-mono font-semibold`}>
        {row.number}
      </th>
      <td data-label={t("projects.pinUsage.columns.label")} className={netCell}>
        {row.label ?? <span className="text-muted">—</span>}
      </td>
      <td data-label={t("projects.pinUsage.columns.nets")} className={netCell}>
        {row.uses.length === 0 ? (
          <span className="text-muted">{t("projects.pinUsage.free")}</span>
        ) : (
          <ul className="grid gap-1">
            {row.uses.map((use) => (
              <li
                key={`${use.net_id}:${use.designator}`}
                className="flex flex-wrap items-baseline gap-x-2"
              >
                <span className="font-semibold">{use.net_name}</span>
                <WireSwatch color={use.color} />
                <span className="font-mono text-muted">{use.designator}</span>
                <Link
                  to="/projects/$projectId/revisions/$revisionId"
                  params={{ projectId: use.project_id, revisionId: use.revision_id }}
                  hash={`net-${use.net_id}`}
                  className="text-primary hover:underline"
                >
                  {t("projects.holdings.revisionName", {
                    project: use.project_name,
                    revision: use.revision_label,
                  })}
                </Link>
                <span className="text-muted">
                  {t(statusKey(use.status)).toLocaleLowerCase(i18n.language)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

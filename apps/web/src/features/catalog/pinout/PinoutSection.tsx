import type { PartDetails, Pin } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan, StackedTable } from "../../../shared/ui/block";
import { usePinout } from "./pinout";

const COLUMNS = ["number", "label", "type", "functions", "voltage"] as const;
const cell = "py-1 pr-3 align-top last:pr-0";

type PinoutSectionProps = {
  part: PartDetails;
  /**
   * Opens the editor. The section only reads, so whoever has an editor to open passes this;
   * without it the table is shown and nothing offers to change it.
   */
  onEdit?: () => void;
  span?: BlockSpan | undefined;
};

/**
 * A part's pin table as it reads: one row per pin, narrowed by a filter that matches the
 * number, the label or an alternate function, so `SDA` finds the pin labelled `SDI`
 * (requirements 5.1 to 5.3).
 */
export function PinoutSection({ part, onEdit, span }: PinoutSectionProps) {
  const { t } = useTranslation();
  // A part with no pins says so from what the part page already loaded; nothing is fetched.
  const pinout = usePinout(part.id, { enabled: part.pin_count > 0 });
  const [filter, setFilter] = useState("");
  const filterId = useId();

  const pins = pinout.data?.pins ?? [];
  const empty = part.pin_count === 0 || (pinout.isSuccess && pins.length === 0);
  const shown = matching(pins, filter);

  return (
    <Block title={t("catalog.pinout.title")} span={span}>
      {pinout.isLoading && <p className="text-muted">{t("catalog.pinout.loading")}</p>}
      {pinout.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.pinout.error")}
        </p>
      )}
      {empty && <p className="text-muted">{t("catalog.pinout.none")}</p>}

      {pins.length > 0 && (
        <>
          <div className="grid gap-1 sm:max-w-xs">
            <label htmlFor={filterId} className="text-sm font-medium">
              {t("catalog.pinout.filter")}
            </label>
            <input
              id={filterId}
              type="search"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              className="rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
            />
          </div>
          <StackedTable below="xs">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border text-sm text-muted">
                  {COLUMNS.map((column) => (
                    <th key={column} scope="col" className={`${cell} font-medium`}>
                      {t(`catalog.pinout.columns.${column}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((pin) => (
                  <tr key={pin.number} className="border-b border-border last:border-0">
                    {/* Unlabelled: the pin's number is its card's title once the table stacks. */}
                    <td className={`${cell} font-mono tabular-nums`}>{pin.number}</td>
                    <td
                      data-label={t("catalog.pinout.columns.label")}
                      className={`${cell} font-mono`}
                    >
                      {pin.label}
                    </td>
                    <td data-label={t("catalog.pinout.columns.type")} className={cell}>
                      {t(`catalog.pinout.types.${pin.type}`)}
                    </td>
                    <td
                      data-label={t("catalog.pinout.columns.functions")}
                      className={`${cell} font-mono text-sm`}
                    >
                      {pin.functions.join(" ") || "—"}
                    </td>
                    <td
                      data-label={t("catalog.pinout.columns.voltage")}
                      className={`${cell} tabular-nums`}
                    >
                      {pin.voltage?.display ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </StackedTable>
          {shown.length === 0 && <p className="text-muted">{t("catalog.pinout.noMatches")}</p>}
        </>
      )}

      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {empty ? t("catalog.pinout.add") : t("catalog.pinout.edit")}
        </button>
      )}
    </Block>
  );
}

/** A filter matches a pin's number, its label or one of its alternate functions (5.3). */
function matching(pins: Pin[], filter: string): Pin[] {
  const needle = filter.trim().toLowerCase();
  if (needle === "") return pins;
  return pins.filter((pin) =>
    [pin.number, pin.label, ...pin.functions].some((text) => text.toLowerCase().includes(needle)),
  );
}

import { Link } from "@tanstack/react-router";
import type { BlockingFlash } from "@wiredex/api-client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useTimeFormat } from "./flashes";
import { RemoveFlash } from "./RemoveFlash";

/**
 * The flashes that keep a version or a firmware from being deleted (requirement 8.7), under
 * the refusal that names them: each unit's code, a link while inventory still holds the unit,
 * the version and when it was flashed, and *Remove*, which asks in its row. A deleted unit's
 * page is gone, so this is where its entries are cleared (decision 6). A removed entry leaves
 * the list at once, the refusal itself being the delete's and not refetched; once none is left
 * a line says the delete can go ahead.
 */
export function BlockingFlashes({ flashes }: { flashes: readonly BlockingFlash[] }) {
  const { t } = useTranslation();
  const format = useTimeFormat();
  const [removed, setRemoved] = useState<ReadonlySet<string>>(() => new Set());
  const left = flashes.filter((flash) => !removed.has(flash.id));

  return (
    <div className="grid gap-2">
      {left.length > 0 && (
        <ul aria-label={t("firmware.flash.blocking.label")} className="grid gap-2">
          {left.map((flash) => {
            const when = format(flash.flashed_at);
            return (
              <li
                key={flash.id}
                className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-border pb-2 text-sm"
              >
                <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 py-1.5">
                  {flash.unit_present ? (
                    <Link
                      to="/units/$unitId"
                      params={{ unitId: flash.unit.id }}
                      className="font-mono text-primary hover:underline"
                    >
                      {flash.unit.code}
                    </Link>
                  ) : (
                    <span>
                      <span className="font-mono">{flash.unit.code}</span>{" "}
                      <span className="text-muted">{t("firmware.flash.blocking.gone")}</span>
                    </span>
                  )}
                  <span>
                    {t("firmware.flash.blocking.entry", {
                      version: flash.version.version,
                      date: when,
                    })}
                  </span>
                </span>
                <RemoveFlash
                  flashId={flash.id}
                  label={t("firmware.flash.blocking.removeEntry", {
                    version: flash.version.version,
                    code: flash.unit.code,
                    date: when,
                  })}
                  onRemoved={() => setRemoved((before) => new Set(before).add(flash.id))}
                />
              </li>
            );
          })}
        </ul>
      )}
      {/* Present from the start, so the line is announced when the last entry goes. */}
      <p role="status" className="text-sm">
        {left.length === 0 && t("firmware.flash.blocking.cleared")}
      </p>
    </div>
  );
}

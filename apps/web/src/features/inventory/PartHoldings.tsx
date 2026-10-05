import { useId } from "react";
import { useTranslation } from "react-i18next";
import { usePartHoldings } from "../projects/build/lifecycle";
import { RevisionRefLink } from "../projects/build/RevisionLink";

type Props = { partId: string };

/**
 * The builds holding a part, shown under its stock breakdown (requirement 13.8): each revision
 * that reserves or has consumed some of it, linking to the revision, with how many it reserves
 * and how many its build consumed. The holdings ride the lifecycle cache, so a transition
 * refreshes this in place (requirement 13.7). While no build holds any, the section stays but
 * says so; a part never reserved simply reads empty.
 */
export function PartHoldings({ partId }: Props) {
  const { t } = useTranslation();
  const headingId = useId();
  const holdings = usePartHoldings(partId);
  const rows = holdings.data ?? [];

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-2">
      <h3 id={headingId} className="font-semibold">
        {t("inventory.holdings.title")}
      </h3>
      {holdings.isPending && <p className="text-muted">{t("inventory.holdings.loading")}</p>}
      {holdings.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.holdings.error")}
        </p>
      )}
      {holdings.data && rows.length === 0 && (
        <p className="text-muted">{t("inventory.holdings.none")}</p>
      )}
      {rows.length > 0 && (
        <ul className="grid gap-2">
          {rows.map((holding) => (
            <li
              key={holding.revision.id}
              className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-1 text-sm"
            >
              <RevisionRefLink revision={holding.revision} />
              <span className="text-muted">
                {holding.consumed > 0
                  ? t("inventory.holdings.consumed", { count: holding.consumed })
                  : t("inventory.holdings.reserved", { count: holding.reserved })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

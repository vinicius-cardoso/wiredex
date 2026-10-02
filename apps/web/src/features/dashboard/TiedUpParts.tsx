import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { TiedUpPart, TiedUpParts } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { RevisionRefLink } from "../projects/build/RevisionLink";
import { Panel, PanelStates } from "./Panel";

/**
 * The stock reserved and built revisions hold, the most tied up first (requirement 1): each part
 * linking to its page, how many are reserved and how many are in builds, and each revision
 * holding it with its share, linking to the revision. Past the page, how many more there are.
 */
export function TiedUpPartsPanel({ query }: { query: UseQueryResult<TiedUpParts> }) {
  const { t } = useTranslation();
  const parts = query.data?.parts ?? [];
  const more = query.data?.more ?? 0;

  return (
    <Panel title={t("dashboard.tiedUp.title")} intro={t("dashboard.tiedUp.intro")}>
      <PanelStates
        query={query}
        loading={t("dashboard.tiedUp.loading")}
        error={t("dashboard.tiedUp.error")}
        empty={parts.length === 0 ? t("dashboard.tiedUp.empty") : null}
      />
      {parts.length > 0 && (
        <ul aria-label={t("dashboard.tiedUp.list")} className="grid gap-3">
          {parts.map((part) => (
            <TiedUpItem key={part.part_id} part={part} />
          ))}
        </ul>
      )}
      {more > 0 && (
        <p className="text-sm text-muted">{t("dashboard.tiedUp.more", { count: more })}</p>
      )}
    </Panel>
  );
}

function TiedUpItem({ part }: { part: TiedUpPart }) {
  const { t } = useTranslation();
  const counts = [
    part.reserved > 0 && t("dashboard.tiedUp.reserved", { count: part.reserved }),
    part.consumed > 0 && t("dashboard.tiedUp.inBuilds", { count: part.consumed }),
  ].filter(Boolean);

  return (
    <li className="grid min-w-0 gap-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <Link
          to="/parts/$partId"
          params={{ partId: part.part_id }}
          className={`font-medium wrap-anywhere hover:underline ${part.part ? "text-primary" : "text-warn"}`}
        >
          {part.part?.name ?? t("projects.bom.unknownPart")}
        </Link>
        <span className="text-sm text-muted tabular-nums">{counts.join(" · ")}</span>
      </div>
      <ul
        aria-label={t("dashboard.tiedUp.revisions", {
          part: part.part?.name ?? t("projects.bom.unknownPart"),
        })}
        className="grid gap-0.5 border-l-2 border-border pl-3 text-sm"
      >
        {part.revisions.map((holding) => (
          <li
            key={holding.revision.id}
            className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2"
          >
            <RevisionRefLink revision={holding.revision} />
            <span className="text-muted tabular-nums">
              {holding.consumed > 0
                ? t("inventory.holdings.consumed", { count: holding.consumed })
                : t("inventory.holdings.reserved", { count: holding.reserved })}
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}

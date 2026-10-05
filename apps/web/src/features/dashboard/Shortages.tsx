import type { UseQueryResult } from "@tanstack/react-query";
import type { BomPart, ShortRevision, ShortRevisions } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { PartLink } from "../projects/bom/ShortageReport";
import { stockStatusKey, stockStatusTone } from "../projects/bom/stockStatus";
import { RevisionRefLink } from "../projects/build/RevisionLink";
import { Panel, PanelStates } from "./Panel";

/**
 * The drafts whose BOM is short of a stocked part or names one the catalog no longer holds, by
 * project and label (requirement 2): each linking to its revision, with how many parts it is
 * missing, then each of those parts linking to its page, with its need, its stock and the
 * shortfall, as the draft's own BOM report gives them. The panel lists the first few drafts, and
 * says how many more there are.
 */
export function ShortagesPanel({ query }: { query: UseQueryResult<ShortRevisions> }) {
  const { t } = useTranslation();
  const revisions = query.data?.revisions ?? [];
  const more = query.data?.more ?? 0;

  return (
    <Panel title={t("dashboard.shortages.title")} intro={t("dashboard.shortages.intro")}>
      <PanelStates
        query={query}
        loading={t("dashboard.shortages.loading")}
        error={t("dashboard.shortages.error")}
        empty={revisions.length === 0 ? t("dashboard.shortages.empty") : null}
      />
      {revisions.length > 0 && (
        <ul aria-label={t("dashboard.shortages.list")} className="grid gap-3">
          {revisions.map((short) => (
            <ShortItem key={short.revision.id} short={short} />
          ))}
        </ul>
      )}
      {more > 0 && (
        <p className="text-sm text-muted">{t("dashboard.shortages.more", { count: more })}</p>
      )}
    </Panel>
  );
}

function ShortItem({ short }: { short: ShortRevision }) {
  const { t } = useTranslation();
  const missing = short.summary.short_parts + short.summary.unknown_parts;

  return (
    <li className="grid min-w-0 gap-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <RevisionRefLink revision={short.revision} />
        <span className="text-sm text-muted tabular-nums">
          {t("dashboard.shortages.missing", { count: missing })}
        </span>
      </div>
      <ul
        aria-label={t("dashboard.shortages.parts", {
          project: short.revision.project_name,
          revision: short.revision.label,
        })}
        className="grid gap-0.5 border-l-2 border-border pl-3 text-sm"
      >
        {short.parts.map((part) => (
          <li
            key={part.part_id}
            className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2"
          >
            <PartLink part={part} />
            <MissingCount part={part} />
          </li>
        ))}
      </ul>
    </li>
  );
}

/** A short part's shortfall with its need and stock; an unknown part says only that. */
function MissingCount({ part }: { part: BomPart }) {
  const { t } = useTranslation();
  if (part.status !== "short") {
    return <span className={stockStatusTone[part.status]}>{t(stockStatusKey(part.status))}</span>;
  }
  return (
    <span className="tabular-nums">
      <span className={`font-semibold ${stockStatusTone.short}`}>
        {t("dashboard.shortages.short", { count: part.short })}
      </span>{" "}
      <span className="text-muted">
        {t("dashboard.shortages.needHave", { need: part.need, available: part.available ?? 0 })}
      </span>
    </span>
  );
}

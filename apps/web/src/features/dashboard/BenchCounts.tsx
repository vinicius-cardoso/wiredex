import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import type { BenchCounts } from "./dashboard";

const TILES = [
  { kind: "parts", to: "/parts" },
  { kind: "boards", to: "/units" },
  { kind: "projects", to: "/projects" },
  { kind: "firmware", to: "/firmware" },
  { kind: "locations", to: "/locations" },
] as const;

/**
 * What the bench holds, one tile for each kind of record, each linking to its list. A count
 * that hasn't arrived, or couldn't be read, shows a dash: the tiles are still the way in.
 */
export function BenchCountTiles({ query }: { query: UseQueryResult<BenchCounts> }) {
  const { t, i18n } = useTranslation();
  const format = new Intl.NumberFormat(i18n.language);

  return (
    <nav aria-label={t("dashboard.counts.title")}>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {TILES.map(({ kind, to }) => (
          <li key={kind} className="min-w-0">
            <Link
              to={to}
              className="grid gap-0.5 rounded-lg border border-border bg-surface px-4 py-3 hover:border-border-strong hover:bg-surface-2"
            >
              <span className="font-display text-2xl font-semibold tabular-nums">
                {query.data ? format.format(query.data[kind]) : "–"}
              </span>{" "}
              <span className="text-sm text-muted">{t(`dashboard.counts.${kind}`)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

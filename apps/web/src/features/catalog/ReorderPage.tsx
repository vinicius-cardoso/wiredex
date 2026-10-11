import { Link } from "@tanstack/react-router";
import type { ReorderLine } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { StackedTable } from "../../shared/ui/block";
import { useReorderList } from "./reorder";

const cell = "py-2 pr-4 align-top last:pr-0";

/**
 * What to buy (spec 24): every part below the minimum set for it, the emptiest first, with
 * what there is, the minimum and how many are missing. It says what "there is" means here,
 * free stock or everything on hand, and where to change that; a part with no minimum is never
 * listed, so an empty list says how to start.
 */
export function ReorderPage() {
  const { t } = useTranslation();
  const reorder = useReorderList();
  const items = reorder.data?.items ?? [];

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("reorder.title")}</h1>
      <p className="max-w-prose text-muted">{t("reorder.intro")}</p>
      {reorder.isPending && <p className="text-muted">{t("reorder.loading")}</p>}
      {reorder.isError && (
        <p role="alert" className="text-crit">
          {t("reorder.error")}
        </p>
      )}
      {reorder.data && (
        <p className="text-sm">
          {t(`reorder.basis.${reorder.data.basis}`)}{" "}
          <Link to="/settings" className="font-semibold text-primary hover:underline">
            {t("reorder.changeBasis")}
          </Link>
        </p>
      )}
      {reorder.data && items.length === 0 && (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {t("reorder.empty")}
        </p>
      )}
      {items.length > 0 && (
        <>
          <p className="text-sm text-muted">{t("reorder.count", { count: items.length })}</p>
          <StackedTable below="md">
            <table className="w-full border-collapse text-left">
              <caption className="sr-only">{t("reorder.caption")}</caption>
              <thead>
                <tr className="border-b border-border text-sm text-muted">
                  <th scope="col" className={`${cell} font-medium`}>
                    {t("reorder.columns.part")}
                  </th>
                  <th scope="col" className={`${cell} font-medium`}>
                    {t("reorder.columns.category")}
                  </th>
                  <th scope="col" className={`${cell} text-right font-medium`}>
                    {t(`reorder.columns.have.${reorder.data?.basis ?? "free"}`)}
                  </th>
                  <th scope="col" className={`${cell} text-right font-medium`}>
                    {t("reorder.columns.minimum")}
                  </th>
                  <th scope="col" className={`${cell} text-right font-medium`}>
                    {t("reorder.columns.missing")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((line) => (
                  <Row key={line.part_id} line={line} basis={reorder.data?.basis ?? "free"} />
                ))}
              </tbody>
            </table>
          </StackedTable>
        </>
      )}
    </section>
  );
}

function Row({ line, basis }: { line: ReorderLine; basis: "free" | "total" }) {
  const { t } = useTranslation();

  return (
    <tr className="border-b border-border last:border-0">
      <th scope="row" data-label={t("reorder.columns.part")} className={`${cell} font-normal`}>
        <Link
          to="/parts/$partId"
          params={{ partId: line.part_id }}
          className="font-semibold text-primary hover:underline"
        >
          {line.name}
        </Link>
        {line.mpn && <span className="block text-sm text-muted">{line.mpn}</span>}
      </th>
      <td data-label={t("reorder.columns.category")} className={cell}>
        {line.category.name}
      </td>
      <td
        data-label={t(`reorder.columns.have.${basis}`)}
        className={`${cell} text-right tabular-nums ${line.have === 0 ? "font-semibold text-crit" : ""}`}
      >
        {line.have}
      </td>
      <td data-label={t("reorder.columns.minimum")} className={`${cell} text-right tabular-nums`}>
        {line.minimum}
        {line.minimum_from && (
          <span className="block text-sm text-muted">
            {t("reorder.fromCategory", { category: line.minimum_from.name })}
          </span>
        )}
      </td>
      <td
        data-label={t("reorder.columns.missing")}
        className={`${cell} text-right font-semibold tabular-nums text-warn`}
      >
        {line.missing}
      </td>
    </tr>
  );
}

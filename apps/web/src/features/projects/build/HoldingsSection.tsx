import { Link } from "@tanstack/react-router";
import type { HeldPart, RevisionStatus } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan } from "../../../shared/ui/block";
import { useLifecycle } from "./lifecycle";
import { holdsStock } from "./transitions";

type Props = { revisionId: string; status: RevisionStatus; span?: BlockSpan | undefined };

/**
 * What a reserved or built revision holds (requirement 13.6): each part it holds, with its
 * quantity and, while reserved, the locations it is set aside in, or its quantity in the build
 * while built; and each unit's code linking to the unit's page. A draft or a dismantled
 * revision holds nothing, so the section shows only when the status holds stock; the lifecycle
 * read keeps it current, so a transition refreshes it in place (requirement 13.7). The list
 * scrolls inside its own box, so a phone never scrolls the page sideways (requirement 13.16).
 */
export function HoldingsSection({ revisionId, status, span }: Props) {
  const { t } = useTranslation();
  const lifecycle = useLifecycle(revisionId);

  if (!holdsStock(status)) return null;

  const parts = lifecycle.data?.parts ?? [];

  return (
    <Block
      level={3}
      span={span}
      title={t(
        status === "built" ? "projects.holdings.builtTitle" : "projects.holdings.reservedTitle",
      )}
    >
      {lifecycle.isPending && <p className="text-muted">{t("projects.holdings.loading")}</p>}
      {lifecycle.isError && (
        <p role="alert" className="text-crit">
          {t("projects.holdings.error")}
        </p>
      )}
      {lifecycle.data && parts.length === 0 && (
        <p className="text-muted">{t("projects.holdings.empty")}</p>
      )}
      {parts.length > 0 && (
        <ul className="grid gap-3">
          {parts.map((part) => (
            <HeldPartRow key={part.part_id} part={part} status={status} />
          ))}
        </ul>
      )}
    </Block>
  );
}

/** One part the revision holds: its name, its quantity, where it sits, and its units. */
function HeldPartRow({ part, status }: { part: HeldPart; status: RevisionStatus }) {
  const { t } = useTranslation();
  const reserved = part.reserved.reduce((sum, at) => sum + at.quantity, 0);
  const quantity = status === "built" ? part.consumed : reserved;

  return (
    <li className="grid gap-1 rounded-md border border-border bg-surface-2 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">
          {part.part ? (
            <Link
              to="/parts/$partId"
              params={{ partId: part.part_id }}
              className="text-primary hover:underline"
            >
              {part.part.name}
            </Link>
          ) : (
            <Link
              to="/parts/$partId"
              params={{ partId: part.part_id }}
              className="text-warn hover:underline"
            >
              {t("projects.bom.unknownPart")}
            </Link>
          )}
        </span>
        <span className="text-sm text-muted">
          {status === "built"
            ? t("projects.holdings.inBuild", { count: quantity })
            : t("projects.holdings.setAside", { count: quantity })}
        </span>
      </div>

      {status === "reserved" && part.reserved.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
          {part.reserved.map((at) => (
            <li key={at.location_id}>
              {t("projects.holdings.atLocation", {
                code: at.location_code,
                count: at.quantity,
              })}
            </li>
          ))}
        </ul>
      )}

      {part.units.length > 0 && (
        <ul className="flex flex-wrap gap-2 text-sm">
          {part.units.map((unit) => (
            <li key={unit.unit_id}>
              <Link
                to="/units/$unitId"
                params={{ unitId: unit.unit_id }}
                className="font-mono text-primary hover:underline"
              >
                {unit.code}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

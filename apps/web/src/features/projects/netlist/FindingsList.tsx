import type { Finding, Severity } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { errorsFirst, findingMessage } from "./findings";

/**
 * What the wiring rules found, under the nets (spec 12, requirement 10.1): errors first, each
 * with its severity in words and an icon, its sentence, and links to the net rows it names; a
 * line when there is nothing to report.
 */
export function FindingsList({ findings }: { findings: readonly Finding[] }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-2">
      <h4 id={headingId} className="font-semibold">
        {t("projects.netlist.findings.title")}
      </h4>
      {findings.length === 0 ? (
        <p className="text-sm text-muted">{t("projects.netlist.findings.none")}</p>
      ) : (
        <ul className="grid gap-1 text-sm">
          {errorsFirst(findings).map((finding) => (
            <li
              key={`${finding.code}:${finding.net_ids.join(",")}:${finding.refs.join(",")}`}
              className="flex min-w-0 flex-wrap items-baseline gap-x-2"
            >
              <SeverityLabel severity={finding.severity} />
              <span className="min-w-0 break-words">
                {findingMessage(t, i18n.language, finding)}
              </span>
              {finding.nets.length > 0 && (
                <span className="flex flex-wrap gap-x-2">
                  <span className="text-muted">{t("projects.netlist.findings.nets")}</span>
                  {finding.nets.map((net, index) => (
                    <a
                      key={finding.net_ids[index]}
                      href={`#net-${finding.net_ids[index]}`}
                      className="font-mono text-primary hover:underline"
                    >
                      {net}
                    </a>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** A severity in words beside its icon, never by colour alone (requirement 10.2). */
export function SeverityLabel({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  const error = severity === "error";
  return (
    <span className={`text-xs font-semibold ${error ? "text-crit" : "text-warn"}`}>
      <span aria-hidden="true">{error ? "✖ " : "⚠ "}</span>
      {t(`projects.netlist.findings.severity.${severity}`)}
    </span>
  );
}

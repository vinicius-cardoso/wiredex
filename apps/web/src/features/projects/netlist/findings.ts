import type { Finding, Severity } from "@wiredex/api-client";
import type { TFunction } from "i18next";

/** Errors first, keeping the API's order within each severity (spec 12, requirement 1.3). */
export function errorsFirst(findings: readonly Finding[]): Finding[] {
  return [...findings].sort((a, b) => rank(a.severity) - rank(b.severity));
}

/**
 * The worst severity of the findings naming each reference, by its canonical text, so a chip
 * can say it (requirement 10.2).
 */
export function severityByRef(findings: readonly Finding[]): ReadonlyMap<string, Severity> {
  const worst = new Map<string, Severity>();
  for (const finding of findings) {
    for (const ref of finding.refs) {
      const known = worst.get(ref);
      if (!known || rank(finding.severity) < rank(known)) worst.set(ref, finding.severity);
    }
  }
  return worst;
}

/**
 * A finding's sentence in the reader's language, from its code and fields: the API's
 * `message` is English only. The nets are left out; the list links them beside the sentence.
 */
export function findingMessage(t: TFunction, language: string, finding: Finding): string {
  const list = (items: readonly string[]) =>
    new Intl.ListFormat(language, { type: "conjunction" }).format(items);
  const [first] = finding.refs;
  const [designator, pin] = splitRef(first ?? "");
  const volts = new Intl.NumberFormat(language, { maximumFractionDigits: 3 });
  return t(`projects.netlist.findings.messages.${finding.code}`, {
    ref: first,
    refs: list(finding.refs),
    designator,
    pin,
    part: finding.part_name ?? "",
    designators: finding.designators ?? "",
    nets: list(finding.nets),
    levels: list(finding.levels.map((level) => `${volts.format(Number(level.voltage))} V`)),
  });
}

function splitRef(ref: string): [string, string] {
  const dot = ref.indexOf(".");
  return dot < 0 ? [ref, ""] : [ref.slice(0, dot), ref.slice(dot + 1)];
}

function rank(severity: Severity): number {
  return severity === "error" ? 0 : 1;
}

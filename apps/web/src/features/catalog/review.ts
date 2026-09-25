import type { AttributeProblem } from "@wiredex/api-client";
import type { TFunction } from "i18next";

/**
 * What is wrong with each flagged attribute, keyed by attribute key (requirements 5.3, 7.6).
 *
 * The API reports the problem as one of four names and a message of its own; the name is what
 * gets translated here, so the banner and the field marks read in the reader's language.
 */
export function problemsByKey(problems: AttributeProblem[], t: TFunction): Map<string, string> {
  return new Map(
    problems.map((problem) => [
      problem.key,
      t(`catalog.review.problem.${problem.problem}`, { key: problem.key }),
    ]),
  );
}

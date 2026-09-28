import type { CellProblem } from "@wiredex/api-client";
import type { TFunction } from "i18next";

/**
 * A problem as the reader's language says it (design decision 17).
 *
 * The code picks the sentence, so it reads the same whichever of catalog or inventory found
 * it. The server's own sentence, which stays English, rides along as the detail where only it
 * can say what was wrong: why a value was refused, which categories or locations a path could
 * be, or where a serial is already held. The column fills in the attribute a key names.
 */
export function problemText(problem: CellProblem, t: TFunction): string {
  return t(`inventory.intake.problem.${problem.code}`, {
    detail: problem.message,
    column: problem.column ?? "",
  });
}

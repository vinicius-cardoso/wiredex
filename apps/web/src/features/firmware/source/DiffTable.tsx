import type { SourceFile } from "@wiredex/api-client";
import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { DiffLine, FileComparison, Hunk } from "./compare";
import { type HighlightedLine, highlightLines } from "./highlight";
import { highlightable, languageOf } from "./languages";
import { Tokens } from "./SourceView";

type Props = { file: FileComparison; hunks: Hunk[] };

/** Only a changed line's gutter is tinted, from syntax.css; its text stays on --surface. */
const GUTTER = {
  added: "diff-gutter-added",
  removed: "diff-gutter-removed",
  context: "",
} as const satisfies Record<DiffLine["kind"], string>;

const NUMBER = "px-2 py-1 text-right font-normal whitespace-nowrap";

/**
 * One file's hunks as a table (requirement 5.3): a caption, the old line, the new line, the
 * change and the text, each hunk a row group headed by the lines it spans. A changed line says
 * `+` or `−`, the word for screen readers and a tinted gutter, so colour is never alone (5.1).
 * Lines take their tokens from their side's text highlighted whole, so a comment opened on an
 * unchanged line still colours the changed one inside it (decision 10); a side past the
 * highlighter's limits is shown plain. A long line scrolls inside the table's own box, never
 * the page (requirement 7.3).
 */
export function DiffTable({ file, hunks }: Props) {
  const { t } = useTranslation();
  const captionId = useId();
  const fromRows = useMemo(() => rowsOf(file.from), [file.from]);
  const toRows = useMemo(() => rowsOf(file.to), [file.to]);

  // A removed line is From's; an added or unchanged one is To's, as the version it is now.
  function tokensOf(line: DiffLine): HighlightedLine {
    const [rows, number] =
      line.kind === "removed" ? [fromRows, line.oldNumber] : [toRows, line.newNumber];
    return (number === null ? undefined : rows?.[number - 1]) ?? plain(line.text);
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset groups form controls; this is a box holding a table.
    <div
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a box that scrolls must take focus for the keyboard to scroll it (WCAG 2.1.1).
      tabIndex={0}
      role="group"
      aria-labelledby={captionId}
      className="overflow-x-auto rounded-md border border-border bg-surface"
    >
      <table className="w-max min-w-full border-collapse font-mono text-sm leading-relaxed">
        <caption id={captionId} className="sr-only">
          {t("firmware.compare.caption", { path: file.path })}
        </caption>
        <thead>
          <tr className="font-sans text-xs text-muted">
            <th scope="col" className={NUMBER}>
              {t("firmware.compare.oldLine")}
            </th>
            <th scope="col" className={NUMBER}>
              {t("firmware.compare.newLine")}
            </th>
            <th scope="col" className="px-2 py-1 font-normal whitespace-nowrap">
              {t("firmware.compare.change")}
            </th>
            <th scope="col" className="px-3 py-1 text-left font-normal">
              {t("firmware.compare.text")}
            </th>
          </tr>
        </thead>
        {hunks.map((hunk) => (
          <tbody key={`${hunk.oldStart}:${hunk.newStart}`} className="border-t border-border">
            <tr>
              <th
                scope="rowgroup"
                colSpan={4}
                className="bg-surface-2 px-3 py-1 text-left font-sans text-xs font-normal text-muted"
              >
                <HunkHeading hunk={hunk} />
              </th>
            </tr>
            {hunk.lines.map((line) => (
              // A hunk numbers each line once on each side it is on, so the pair is unique.
              <Row
                key={`${line.oldNumber ?? ""}:${line.newNumber ?? ""}`}
                line={line}
                tokens={tokensOf(line)}
              />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/** *Lines 12–18 → 12–20*; a side with no lines, an added or a removed file's, isn't named. */
function HunkHeading({ hunk }: { hunk: Hunk }) {
  const { t } = useTranslation();
  const from = span(hunk.oldStart, hunk.oldLines);
  const to = span(hunk.newStart, hunk.newLines);
  if (hunk.oldLines === 0) return t("firmware.compare.hunkAdded", { to, count: hunk.newLines });
  if (hunk.newLines === 0) {
    return t("firmware.compare.hunkRemoved", { from, count: hunk.oldLines });
  }
  return t("firmware.compare.hunk", { from, to });
}

function Row({ line, tokens }: { line: DiffLine; tokens: HighlightedLine }) {
  const { t } = useTranslation();
  // Numbers and markers stay out of a selection, so what is selected is the code.
  const gutter = `select-none ${GUTTER[line.kind]}`;

  return (
    <tr>
      <td className={`${gutter} px-2 text-right text-muted`}>{line.oldNumber}</td>
      <td className={`${gutter} px-2 text-right text-muted`}>{line.newNumber}</td>
      <td className={`${gutter} px-2 text-center`}>
        {line.kind !== "context" && (
          <>
            <span aria-hidden="true">{line.kind === "added" ? "+" : "−"}</span>
            <span className="sr-only">
              {t(line.kind === "added" ? "firmware.compare.added" : "firmware.compare.removed")}
            </span>
          </>
        )}
      </td>
      <td className="px-3 whitespace-pre">
        <Tokens tokens={tokens} />
        {line.noFinalNewline && (
          // The space keeps a screen reader from running the note into the line's last word.
          <span className="ps-2 font-sans text-xs text-muted select-none">
            {` ${t("firmware.compare.noFinalNewline")}`}
          </span>
        )}
      </td>
    </tr>
  );
}

function span(start: number, count: number): string {
  return count === 1 ? String(start) : `${start}–${start + count - 1}`;
}

function rowsOf(file: SourceFile | null): HighlightedLine[] | null {
  return file && highlightable(file) ? highlightLines(file.content, languageOf(file.path)) : null;
}

function plain(text: string): HighlightedLine {
  return text === "" ? [] : [{ text, classes: "" }];
}

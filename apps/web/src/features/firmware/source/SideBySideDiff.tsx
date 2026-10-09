import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  type DiffLine,
  type FileComparison,
  type Hunk,
  type SideBySideRow,
  sideBySide,
} from "./compare";
import { HunkHeading, plain, rowsOf } from "./DiffTable";
import type { HighlightedLine } from "./highlight";
import { Tokens } from "./SourceView";
import { changedSpans, marked, type Span } from "./words";

type Props = { file: FileComparison; hunks: Hunk[] };
type Side = "old" | "new";

const NUMBER = "px-2 py-1 text-right font-normal whitespace-nowrap";
const HEADING = "px-3 py-1 text-left font-normal";

/** A side's classes for its changed lines: the gutter's tint, the line's and a changed word's. */
const CHANGED = {
  old: {
    gutter: "diff-gutter-removed",
    line: "diff-line-removed",
    word: "diff-word-removed",
    mark: "−",
    label: "firmware.compare.removed",
  },
  new: {
    gutter: "diff-gutter-added",
    line: "diff-line-added",
    word: "diff-word-added",
    mark: "+",
    label: "firmware.compare.added",
  },
} as const;

/**
 * One file's hunks as an editor shows a diff: the old version on the left, the new on the
 * right, each with its own line numbers. A changed line is tinted across its pane, the words
 * that changed inside it are ruled, and where one side has lines the other lacks, the other is
 * hatched. Still one table, so a screen reader reads a row as the old line then the new, each
 * changed one with `−` or `+` and the word (requirement 5.1). Long lines wrap inside their pane,
 * so the two stay level and nothing scrolls sideways (requirement 7.3).
 */
export function SideBySideDiff({ file, hunks }: Props) {
  const { t } = useTranslation();
  const captionId = useId();
  const fromRows = useMemo(() => rowsOf(file.from), [file.from]);
  const toRows = useMemo(() => rowsOf(file.to), [file.to]);

  function tokensOf(side: Side, line: DiffLine): HighlightedLine {
    const [rows, number] = side === "old" ? [fromRows, line.oldNumber] : [toRows, line.newNumber];
    return (number === null ? undefined : rows?.[number - 1]) ?? plain(line.text);
  }

  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">
      <table
        aria-labelledby={captionId}
        className="w-full table-fixed border-collapse font-mono text-sm leading-relaxed"
      >
        <caption id={captionId} className="sr-only">
          {t("firmware.compare.caption", { path: file.path })}
        </caption>
        <colgroup>
          <col className="w-14" />
          <col className="w-7" />
          <col />
          <col className="w-14" />
          <col className="w-7" />
          <col />
        </colgroup>
        <thead>
          <tr className="font-sans text-xs text-muted">
            <th scope="col" className={NUMBER}>
              <span className="sr-only">{t("firmware.compare.oldLine")}</span>
            </th>
            <th scope="col">
              <span className="sr-only">{t("firmware.compare.change")}</span>
            </th>
            <th scope="col" className={HEADING}>
              {t("firmware.compare.oldText")}
            </th>
            <th scope="col" className={`${NUMBER} border-l border-border`}>
              <span className="sr-only">{t("firmware.compare.newLine")}</span>
            </th>
            <th scope="col">
              <span className="sr-only">{t("firmware.compare.change")}</span>
            </th>
            <th scope="col" className={HEADING}>
              {t("firmware.compare.newText")}
            </th>
          </tr>
        </thead>
        {hunks.map((hunk) => (
          <tbody key={`${hunk.oldStart}:${hunk.newStart}`} className="border-t border-border">
            <tr>
              <th
                scope="rowgroup"
                colSpan={6}
                className="bg-surface-2 px-3 py-1 text-left font-sans text-xs font-normal text-muted"
              >
                <HunkHeading hunk={hunk} />
              </th>
            </tr>
            {sideBySide(hunk).map((row) => (
              <Row
                key={`${row.old?.oldNumber ?? ""}:${row.new?.newNumber ?? ""}`}
                row={row}
                tokensOf={tokensOf}
              />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

type RowProps = { row: SideBySideRow; tokensOf: (side: Side, line: DiffLine) => HighlightedLine };

function Row({ row, tokensOf }: RowProps) {
  // Only a line that replaced another has words to mark; an unchanged one is the same on both.
  const replaced = row.old && row.new && row.old.kind !== "context";
  const spans = replaced ? changedSpans(row.old?.text ?? "", row.new?.text ?? "") : null;
  return (
    <tr className="align-top">
      <Pane side="old" line={row.old} spans={spans?.old ?? []} tokensOf={tokensOf} />
      <Pane side="new" line={row.new} spans={spans?.new ?? []} tokensOf={tokensOf} />
    </tr>
  );
}

type PaneProps = Pick<RowProps, "tokensOf"> & { side: Side; line: DiffLine | null; spans: Span[] };

/** A row's three cells on one side: the line's number, its mark and its text. */
function Pane({ side, line, spans, tokensOf }: PaneProps) {
  const { t } = useTranslation();
  const changed = CHANGED[side];
  // The pane's edge is the line between the two versions.
  const edge = side === "new" ? "border-l border-border" : "";
  if (line === null) {
    return (
      <>
        <td className={`diff-filler ${edge}`} />
        <td className="diff-filler" />
        <td className="diff-filler" />
      </>
    );
  }

  const isChanged = line.kind !== "context";
  // Numbers and markers stay out of a selection, so what is selected is the code.
  const gutter = `select-none ${isChanged ? changed.gutter : ""}`;
  return (
    <>
      <td className={`${gutter} ${edge} px-2 text-right text-muted`}>
        {side === "old" ? line.oldNumber : line.newNumber}
      </td>
      <td className={`${gutter} text-center`}>
        {isChanged && (
          <>
            <span aria-hidden="true">{changed.mark}</span>
            <span className="sr-only">{t(changed.label)}</span>
          </>
        )}
      </td>
      <td className={`${isChanged ? changed.line : ""} px-3 wrap-anywhere whitespace-pre-wrap`}>
        <Tokens tokens={marked(tokensOf(side, line), spans, changed.word)} />
        {line.noFinalNewline && (
          // The space keeps a screen reader from running the note into the line's last word.
          <span className="ps-2 font-sans text-xs text-muted select-none">
            {` ${t("firmware.compare.noFinalNewline")}`}
          </span>
        )}
      </td>
    </>
  );
}

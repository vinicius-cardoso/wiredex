import type { SourceFile } from "@wiredex/api-client";
import { Fragment, type Ref, useMemo } from "react";
import { type HighlightedLine, highlightLines } from "./highlight";
import { languageOf } from "./languages";
import { SourceBox } from "./PlainSource";

type Props = {
  file: SourceFile;
  labelledBy: string;
  wrap: boolean;
  boxRef?: Ref<HTMLPreElement> | undefined;
};

/**
 * A file highlighted in its language, a row per line: its number, then its tokens (decision 4).
 * The numbers are hidden from screen readers and can't be selected, so neither reading nor
 * selecting picks them up (requirement 2.1). Each line keeps its own line break as text, all but
 * a last line the file doesn't end, so the box's code is the stored text character for character.
 * Loaded lazily with its grammars, the first file shown asking for them (decision 5).
 */
export function SourceView({ file, labelledBy, wrap, boxRef }: Props) {
  const rows = useMemo(
    () => highlightLines(file.content, languageOf(file.path)),
    [file.content, file.path],
  );
  const ended = file.content.endsWith("\n");

  return (
    <SourceBox labelledBy={labelledBy} boxRef={boxRef} className="py-3">
      {/* Grid columns line the numbers up; wrapping, the code column takes what is left. */}
      <code
        className={`grid grid-cols-[auto_minmax(0,1fr)] ${
          wrap ? "whitespace-pre-wrap wrap-anywhere" : "w-max min-w-full"
        }`}
      >
        {rows.map((tokens, index) => {
          // A row is its line, so its number keys it.
          const number = index + 1;
          return (
            <Fragment key={number}>
              <span
                aria-hidden="true"
                className="select-none border-r border-border pr-3 pl-3 text-right text-muted"
              >
                {number}
              </span>
              <span className="pr-3 pl-3">
                <Tokens tokens={tokens} />
                {number < rows.length || ended ? "\n" : null}
              </span>
            </Fragment>
          );
        })}
      </code>
    </SourceBox>
  );
}

/** A line's tokens, each styled one keyed by where it starts in the line; a diff's too. */
export function Tokens({ tokens }: { tokens: HighlightedLine }) {
  let offset = 0;
  return tokens.map((token) => {
    const start = offset;
    offset += token.text.length;
    return token.classes ? (
      <span key={start} className={token.classes}>
        {token.text}
      </span>
    ) : (
      token.text
    );
  });
}

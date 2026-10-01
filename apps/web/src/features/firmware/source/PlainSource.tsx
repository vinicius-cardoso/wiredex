import type { SourceFile } from "@wiredex/api-client";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";

type BoxProps = {
  labelledBy: string;
  describedBy?: string | undefined;
  className: string;
  children: ReactNode;
};

/**
 * The box a file's text sits in, plain or highlighted. On --surface, where every token's colour
 * keeps 4.5:1 (decision 3); a long line scrolls inside it, never the page. It scrolls, so it
 * takes focus for the keyboard to scroll it, and it is a group named by the file's heading: a
 * `<pre>` alone is generic, which can't be named, and a region would add a landmark beside the
 * file's own region (requirement 2.4).
 */
export function SourceBox({ labelledBy, describedBy, className, children }: BoxProps) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset groups form controls; this is a box of text.
    <pre
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a box that scrolls must take focus for the keyboard to scroll it (WCAG 2.1.1).
      tabIndex={0}
      role="group"
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      className={`max-h-[32rem] overflow-auto rounded-md border border-border bg-surface font-mono text-sm leading-relaxed ${className}`}
    >
      {children}
    </pre>
  );
}

type Props = { file: SourceFile; labelledBy: string; wrap: boolean; note?: string };

/**
 * A file's text as stored, unnumbered: what shows while the highlighter loads, so the text is
 * never held back (requirement 1.5), and all there is for a file past the highlighter's limits
 * or when it couldn't load, NOTE saying why (requirement 1.4). An empty file says so instead
 * (requirement 2.5).
 */
export function PlainSource({ file, labelledBy, wrap, note }: Props) {
  const { t } = useTranslation();
  const noteId = useId();

  if (file.content === "") {
    return <p className="text-sm text-muted">{t("firmware.source.empty")}</p>;
  }
  return (
    <>
      {note && (
        <p id={noteId} className="text-sm text-muted">
          {note}
        </p>
      )}
      <SourceBox labelledBy={labelledBy} describedBy={note ? noteId : undefined} className="p-3">
        <code className={wrap ? "block whitespace-pre-wrap wrap-anywhere" : undefined}>
          {file.content}
        </code>
      </SourceBox>
    </>
  );
}

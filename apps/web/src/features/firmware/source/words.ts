import { diffWordsWithSpace } from "diff";
import type { HighlightedLine } from "./highlight";

/** Characters `start` up to `end` of a line. */
export type Span = [start: number, end: number];

/** Past this a line is minified or generated, and its words aren't worth the time. */
const MAX_LINE_LENGTH = 500;
/** Below this share of text in common, two lines are different lines, not one edited. */
const MIN_COMMON = 1 / 3;

/**
 * What changed inside a line that replaced another: the spans only the old one has, and the
 * spans only the new one has. Null when marking words would say nothing, because a line is
 * very long or the two share too little to be the same line edited.
 */
export function changedSpans(before: string, after: string): { old: Span[]; new: Span[] } | null {
  if (before.length > MAX_LINE_LENGTH || after.length > MAX_LINE_LENGTH) return null;
  const spans = { old: [] as Span[], new: [] as Span[] };
  let oldAt = 0;
  let newAt = 0;
  let common = 0;
  for (const part of diffWordsWithSpace(before, after)) {
    const length = part.value.length;
    if (part.removed) {
      spans.old.push([oldAt, oldAt + length]);
      oldAt += length;
    } else if (part.added) {
      spans.new.push([newAt, newAt + length]);
      newAt += length;
    } else {
      common += part.value.trim().length;
      oldAt += length;
      newAt += length;
    }
  }
  const longest = Math.max(before.trim().length, after.trim().length);
  return common < longest * MIN_COMMON ? null : spans;
}

/**
 * TOKENS with CLASSES added over SPANS, a token split where a span starts or ends inside it,
 * so a changed word keeps its syntax colour and gains its mark.
 */
export function marked(tokens: HighlightedLine, spans: Span[], classes: string): HighlightedLine {
  if (spans.length === 0) return tokens;
  const result: HighlightedLine = [];
  let at = 0;
  for (const token of tokens) {
    const end = at + token.text.length;
    let from = at;
    for (const [start, stop] of spans) {
      if (stop <= from || start >= end) continue;
      if (start > from)
        result.push({ text: token.text.slice(from - at, start - at), classes: token.classes });
      const until = Math.min(stop, end);
      result.push({
        text: token.text.slice(Math.max(start, from) - at, until - at),
        classes: `${token.classes} ${classes}`.trim(),
      });
      from = until;
    }
    if (from < end) result.push({ text: token.text.slice(from - at), classes: token.classes });
    at = end;
  }
  return result;
}

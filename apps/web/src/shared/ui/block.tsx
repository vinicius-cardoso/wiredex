import { type ReactNode, useId } from "react";

/**
 * The pieces a detail page is built from, so it reads as a grid of cards rather than one long
 * strip. `Block` is a card with a heading that names its landmark; `PageGrid` lays blocks out
 * in one column below xl, two on xl and three on 2xl; `StackedTable` frames a table that turns
 * into labelled cards when its own box is narrow (stacked.css). Nothing a block holds may widen
 * it or a phone page: wide content sits in a frame that scrolls or reflows.
 */

/** How much of its page grid's row a block takes. The grid has one column below xl, two on xl
 *  and, on a page that has three, three on 2xl. */
export type BlockSpan = "one" | "two" | "full" | "xl-row" | "2xl-two";

const SPANS: Record<BlockSpan, string> = {
  one: "",
  // The whole row on xl, two thirds on 2xl.
  two: "xl:col-span-2",
  full: "col-span-full",
  // The third of three small blocks: alone on its row on xl, so it takes the whole row there.
  "xl-row": "xl:col-span-2 2xl:col-span-1",
  // The first of two small blocks: two thirds where three columns fit.
  "2xl-two": "2xl:col-span-2",
};

type BlockProps = {
  /** The heading, which names the landmark. */
  title: string;
  /** Beside the heading, never part of the name (a status chip). */
  badge?: ReactNode | undefined;
  /** The block's own buttons and links, at the heading's right. */
  actions?: ReactNode | undefined;
  span?: BlockSpan | undefined;
  /** Two rows tall while the grid has two columns. */
  tallOnXl?: boolean | undefined;
  /** h2 on a page; h3 inside a group that has its own h2. */
  level?: 2 | 3 | undefined;
  /** A navigation landmark for a block of links (Revisions, Versions). */
  as?: "section" | "nav" | undefined;
  children: ReactNode;
};

export function Block({
  title,
  badge,
  actions,
  span = "one",
  tallOnXl = false,
  level = 2,
  as = "section",
  children,
}: BlockProps) {
  const headingId = useId();
  const Landmark = as;
  const Heading = level === 3 ? "h3" : "h2";
  // `relative` keeps a visually hidden text inside (it is placed absolutely), so it can't
  // escape into main's scroll range. The minmax(0,1fr) column and min-w-0 stop a table's
  // min-content width from widening the block. No overflow, so nothing is clipped, and no
  // z-index, so the header's menu and the dialogs still paint above it.
  return (
    <Landmark
      aria-labelledby={headingId}
      className={`relative grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-lg border border-border bg-surface p-4 ${SPANS[span]} ${tallOnXl ? "xl:row-span-2 2xl:row-span-1" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Heading
          id={headingId}
          className="min-w-0 font-display text-lg font-semibold wrap-anywhere"
        >
          {title}
        </Heading>
        {badge}
        {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </Landmark>
  );
}

type PageGridProps = { columns?: 2 | 3 | undefined; children: ReactNode };

/** A detail page's blocks, in reading order (no dense packing, so focus follows the eye). */
export function PageGrid({ columns = 3, children }: PageGridProps) {
  return (
    <div
      className={`grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-2 ${columns === 3 ? "2xl:grid-cols-3" : ""}`}
    >
      {children}
    </div>
  );
}

/** How narrow a table's box gets before its rows reflow, by how wide its columns need to be:
 *  xs below 24rem, sm below 30rem, md below 44rem, lg below 56rem (stacked.css). */
export type StackBelow = "xs" | "sm" | "md" | "lg";

type StackedTableProps = { below: StackBelow; children: ReactNode };

/**
 * A table's frame, which is also the container its reflow measures: a block's width depends on
 * the grid as much as on the screen. The table must be its direct child. Positioned, so the
 * table's visually hidden caption and head stay inside it.
 */
export function StackedTable({ below, children }: StackedTableProps) {
  return (
    <div data-stack={below} className="relative min-w-0 overflow-x-auto">
      {children}
    </div>
  );
}

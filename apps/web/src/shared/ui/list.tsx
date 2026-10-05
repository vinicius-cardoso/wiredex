import type { ReactNode } from "react";

/**
 * What every list page is built from, so they read alike: a compact header, one bar of filters
 * above the list, and a table that takes the rest of the screen and scrolls inside its own
 * frame on a laptop, with its headings staying in view.
 */

/** The page's section. On a wide screen it fills the main area, so the table can take the rest. */
export const listPage = "flex flex-col gap-3 lg:h-full lg:min-h-0";

type PageHeaderProps = {
  title: string;
  /** One short line saying what the page is for, beside the title where there is room. */
  intro?: string;
  /** The page's buttons, at the right. */
  actions?: ReactNode;
};

export function PageHeader({ title, intro, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
        {intro && <p className="text-sm text-muted">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** One bar of filters: each a small labelled control, side by side, wrapping on a phone. */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <search className="flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border border-border bg-surface px-3 py-2.5">
      {children}
    </search>
  );
}

/** A filter's label above its control. `grow` lets the main search box take the spare width. */
export function FilterField({
  label,
  htmlFor,
  grow = false,
  children,
}: {
  label: string;
  htmlFor: string;
  grow?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`grid gap-1 ${grow ? "min-w-48 flex-1" : ""}`}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

/** A filter bar's input or select. */
export const filterControl =
  "h-9 w-full rounded-md border border-border-strong bg-surface px-2.5 text-sm text-text";

/** A filter bar's plain button: clearing, or opening more filters. */
export const filterButton =
  "inline-flex h-9 items-center gap-1.5 rounded-md border border-border-strong px-3 text-sm hover:bg-surface-2";

/** A page's main button and its quieter neighbour, the size of the compact header. */
export const primaryAction =
  "inline-flex h-9 items-center rounded-md bg-primary px-3.5 text-sm font-semibold text-on-primary hover:opacity-90";
export const secondaryAction =
  "inline-flex h-9 items-center rounded-md border border-border-strong px-3.5 text-sm hover:bg-surface-2";

/**
 * The frame a list's table sits in. On a laptop it takes what is left of the screen and
 * scrolls inside itself; on a phone the page scrolls as usual and the table only sideways.
 * It is positioned because a table's visually hidden caption is placed absolutely: against an
 * unpositioned frame it would escape into `main` and stretch its scroll range on a laptop, where
 * inside the frame it scrolls and clips with the rows.
 */
export function TableFrame({ children }: { children: ReactNode }) {
  return (
    <div className="relative overflow-auto rounded-lg border border-border bg-surface lg:min-h-0 lg:flex-1">
      {children}
    </div>
  );
}

/** The table's own classes, its heading row, and its cells. */
export const listTable = "w-full text-left text-sm";
export const listHead = "sticky top-0 z-10 border-b border-border bg-surface text-muted";
export const listHeadCell = "px-3 py-2 font-medium whitespace-nowrap";
export const listRow = "border-b border-border last:border-b-0 hover:bg-surface-2/60";
export const listCell = "px-3 py-1.5";

/** How many the list holds, said quietly under it or beside its filters. */
export function ListCount({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted">{children}</p>;
}

import type { UseQueryResult } from "@tanstack/react-query";
import { type ReactNode, useId } from "react";

type Props = {
  title: string;
  intro?: string;
  /** A link beside the title, such as the one to the whole activity. */
  action?: ReactNode;
  children: ReactNode;
};

/**
 * One dashboard panel: a titled region of its own, so a screen reader can jump between the
 * three, and a card that keeps its text inside it on a phone (requirements 5.1, 5.6).
 */
export function Panel({ title, intro, action, children }: Props) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className="grid min-w-0 content-start gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id={headingId} className="font-display text-xl font-semibold">
          {title}
        </h2>
        {action}
      </div>
      {intro && <p className="text-sm text-muted">{intro}</p>}
      {children}
    </section>
  );
}

type StatesProps = {
  query: UseQueryResult<unknown>;
  loading: string;
  error: string;
  /** Shown once the panel's read answered nothing. */
  empty: string | null;
};

/** A panel's loading, error and empty states, each its own sentence (requirement 5.1). */
export function PanelStates({ query, loading, error, empty }: StatesProps) {
  if (query.isPending) return <p className="text-muted">{loading}</p>;
  if (query.isError)
    return (
      <p role="alert" className="text-crit">
        {error}
      </p>
    );
  return empty === null ? null : <p className="text-muted">{empty}</p>;
}

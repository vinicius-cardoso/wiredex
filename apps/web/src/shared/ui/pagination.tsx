import { type ReactNode, useEffect, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeftIcon, ChevronRightIcon, ChevronsLeftIcon, ChevronsRightIcon } from "./icons";

/**
 * One bar pages every list: a range, a page size and the page numbers. The page and its size
 * live in the address where a list has one, so a page can be bookmarked and Back walks it.
 */

export const PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 25;

/** Far past any real list, so a hand-typed address can't ask for an absurd offset. */
const MAX_PAGE = 100_000;

/**
 * The page and its size as the address holds them, the defaults left out. Each may be present
 * as `undefined`: the root route has no validator, so the router lays a route's validated
 * search over the raw one, and only a key that is there, even empty, hides a raw `?size=7`.
 */
export type PageSearch = { page?: number | undefined; size?: PageSize | undefined };

/** A param as a whole number: the router parses `?page=2` into 2, a quoted one stays text. */
function wholeNumber(raw: unknown): number | undefined {
  const value = typeof raw === "string" && raw.trim() !== "" ? Number(raw) : raw;
  return typeof value === "number" && Number.isInteger(value) ? value : undefined;
}

/**
 * The page and size from the address. Anything that doesn't fit is dropped, as are the
 * defaults, so a hand-edited link still opens the list and the address stays short. Both keys
 * are always returned, `undefined` when dropped, so a route that spreads this in hides the
 * raw values (see PageSearch); the router leaves `undefined` out of the address.
 */
export function validatePageSearch(raw: Record<string, unknown>): PageSearch {
  const page = wholeNumber(raw.page);
  const size = PAGE_SIZES.find((known) => known === wholeNumber(raw.size));
  return {
    page: page !== undefined && page >= 2 && page <= MAX_PAGE ? page : undefined,
    size: size !== DEFAULT_PAGE_SIZE ? size : undefined,
  };
}

/** The page and size a search asks for, with the defaults filled in. */
export function pageOfSearch(search: PageSearch): { page: number; size: PageSize } {
  return { page: search.page ?? 1, size: search.size ?? DEFAULT_PAGE_SIZE };
}

/** The search with another page and size, the rest kept and the defaults left out. */
export function withPage<S extends PageSearch>(search: S, page: number, size: PageSize): S {
  const { page: _page, size: _size, ...rest } = search;
  return {
    ...rest,
    ...(page > 1 ? { page } : {}),
    ...(size !== DEFAULT_PAGE_SIZE ? { size } : {}),
  } as S;
}

/** The size alone: a new filter or sort starts again at page 1, but at the size chosen. */
export function keepSize(search: PageSearch): { size?: PageSize } {
  return search.size === undefined ? {} : { size: search.size };
}

/** How many pages a list fills; an empty list still has its first. */
export function pageCount(total: number, size: number): number {
  return Math.max(1, Math.ceil(total / size));
}

/** One page of a list held whole, the page clamped to the last one there is. */
export function slicePage<T>(
  items: readonly T[],
  page: number,
  size: number,
): { items: T[]; page: number; total: number } {
  const served = Math.min(Math.max(page, 1), pageCount(items.length, size));
  return {
    items: items.slice((served - 1) * size, served * size),
    page: served,
    total: items.length,
  };
}

/**
 * The page numbers the bar offers: the first, the last, and the current one with a neighbour
 * on each side. A hole of one page shows that page, since a gap would take as much room.
 */
export function pageWindow(page: number, count: number): (number | "gap")[] {
  const wanted = [1, page - 1, page, page + 1, count].filter(
    (candidate) => candidate >= 1 && candidate <= count,
  );
  const pages = [...new Set(wanted)].sort((a, b) => a - b);
  const window: (number | "gap")[] = [];
  for (const [index, current] of pages.entries()) {
    const previous = pages[index - 1];
    if (previous !== undefined && current - previous === 2) window.push(previous + 1);
    else if (previous !== undefined && current - previous > 2) window.push("gap");
    window.push(current);
  }
  return window;
}

/**
 * Moves the address to the page the list actually served, when the one asked for is past the
 * end. An API list passes its served page only once it is its own, not a placeholder from
 * the previous page, or the address would bounce back.
 */
export function useClampedPage(
  requested: number,
  served: number | undefined,
  onClamp: (served: number) => void,
): void {
  const latest = useRef(onClamp);
  useEffect(() => {
    latest.current = onClamp;
  });
  useEffect(() => {
    if (served !== undefined && served !== requested) latest.current(served);
  }, [requested, served]);
}

type PaginationProps = {
  /** The bar's name, saying which list it pages. */
  label: string;
  total: number;
  page: number;
  size: PageSize;
  /** The one callback: a new page, a new size, or both. */
  onChange: (page: number, size: PageSize) => void;
};

const pageButton =
  "inline-flex h-8 min-w-7 items-center justify-center rounded-md border border-border-strong px-1.5 hover:bg-surface-2 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 aria-[current=page]:border-primary aria-[current=page]:bg-primary aria-[current=page]:font-semibold aria-[current=page]:text-on-primary";

/**
 * The bar over a list, under its filters, so the page and its size are at hand before the
 * rows and stay put however long the page is. It shows whenever the list holds something; a button that can't act
 * says so with `aria-disabled` and keeps its focus, so the keyboard isn't thrown back to the
 * top of the page when the last page is reached.
 */
export function Pagination({ label, total, page, size, onChange }: PaginationProps) {
  const { t, i18n } = useTranslation();
  const sizeId = useId();
  if (total === 0) return null;

  const count = pageCount(total, size);
  const current = Math.min(Math.max(page, 1), count);
  const first = (current - 1) * size + 1;
  const last = Math.min(current * size, total);
  const number = new Intl.NumberFormat(i18n.language);

  function go(next: number) {
    if (next !== current) onChange(next, size);
  }

  function resize(value: string) {
    const next = PAGE_SIZES.find((known) => known === Number(value));
    if (next === undefined || next === size) return;
    // The first row on screen stays on screen.
    onChange(Math.floor(((current - 1) * size) / next) + 1, next);
  }

  return (
    <nav
      aria-label={label}
      data-tour="pages"
      className="@container flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm lg:shrink-0"
    >
      <p aria-live="polite" className="tabular-nums text-muted">
        {t("pagination.range", { first, last, total })}
      </p>
      <div className="flex items-center gap-2">
        <label htmlFor={sizeId} className="text-muted">
          {t("pagination.size")}
        </label>
        <select
          id={sizeId}
          value={size}
          onChange={(event) => resize(event.target.value)}
          className="h-8 rounded-md border border-border-strong bg-surface px-2 text-sm text-text"
        >
          {PAGE_SIZES.map((option) => (
            <option key={option} value={option}>
              {number.format(option)}
            </option>
          ))}
        </select>
      </div>
      <ul className="flex flex-wrap items-center gap-0.5 @md:gap-1">
        <PageButton label={t("pagination.first")} disabled={current === 1} onClick={() => go(1)}>
          <ChevronsLeftIcon />
        </PageButton>
        <PageButton
          label={t("pagination.previous")}
          disabled={current === 1}
          onClick={() => go(current - 1)}
        >
          <ChevronLeftIcon />
        </PageButton>
        {pageWindow(current, count).map((slot, index) =>
          slot === "gap" ? (
            // Gaps are keyed by position, numbers by their number, so a clicked number keeps
            // its node and its focus.
            // biome-ignore lint/suspicious/noArrayIndexKey: a gap has nothing else to be known by
            <li key={`gap-${index}`} aria-hidden="true" className="px-1 text-muted">
              …
            </li>
          ) : (
            <PageButton
              key={slot}
              label={t("pagination.page", { page: slot })}
              current={slot === current}
              onClick={() => go(slot)}
            >
              <span className="tabular-nums">{number.format(slot)}</span>
            </PageButton>
          ),
        )}
        <PageButton
          label={t("pagination.next")}
          disabled={current === count}
          onClick={() => go(current + 1)}
        >
          <ChevronRightIcon />
        </PageButton>
        <PageButton
          label={t("pagination.last")}
          disabled={current === count}
          onClick={() => go(count)}
        >
          <ChevronsRightIcon />
        </PageButton>
      </ul>
    </nav>
  );
}

function PageButton({
  label,
  disabled = false,
  current = false,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  current?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        aria-label={label}
        aria-disabled={disabled || undefined}
        aria-current={current ? "page" : undefined}
        onClick={() => {
          if (!disabled) onClick();
        }}
        className={pageButton}
      >
        {children}
      </button>
    </li>
  );
}

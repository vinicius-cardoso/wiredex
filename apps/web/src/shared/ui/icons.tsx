import type { ReactNode } from "react";

/**
 * The app's small line icons, drawn here rather than pulled from a library: ten shapes don't
 * earn a dependency. Each is decoration beside a name the control already carries, so they are
 * hidden from assistive technology.
 */
function Icon({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

export function SunIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Icon>
  );
}

export function MoonIcon() {
  return (
    <Icon>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </Icon>
  );
}

export function MonitorIcon() {
  return (
    <Icon>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </Icon>
  );
}

export function SearchIcon() {
  return (
    <Icon>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </Icon>
  );
}

export function PlusIcon() {
  return (
    <Icon>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

export function DevicesIcon() {
  return (
    <Icon>
      <rect x="2" y="4" width="14" height="10" rx="2" />
      <path d="M6 18h6M9 14v4" />
      <rect x="17" y="9" width="5" height="11" rx="1.5" />
    </Icon>
  );
}

export function CompassIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="9" />
      <path d="M15.5 8.5l-2 5-5 2 2-5z" />
    </Icon>
  );
}

export function LogOutIcon() {
  return (
    <Icon>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
    </Icon>
  );
}

/** A tree branch's fold: points right while folded, and is turned down when open. */
export function ChevronRightIcon() {
  return (
    <Icon size={14}>
      <path d="M9 6l6 6-6 6" />
    </Icon>
  );
}

/** A step back, as a list's previous page. */
export function ChevronLeftIcon() {
  return (
    <Icon size={14}>
      <path d="M15 6l-6 6 6 6" />
    </Icon>
  );
}

/** All the way back, as a list's first page. */
export function ChevronsLeftIcon() {
  return (
    <Icon size={14}>
      <path d="M11 6l-6 6 6 6M18 6l-6 6 6 6" />
    </Icon>
  );
}

/** All the way forward, as a list's last page. */
export function ChevronsRightIcon() {
  return (
    <Icon size={14}>
      <path d="M13 6l6 6-6 6M6 6l6 6-6 6" />
    </Icon>
  );
}

/** Opens a block to its full detail: two chevrons pointing apart. */
export function ExpandIcon() {
  return (
    <Icon>
      <path d="M7 15l5 5 5-5M7 9l5-5 5 5" />
    </Icon>
  );
}

/** Folds a block back to its summary: two chevrons pointing together. */
export function CollapseIcon() {
  return (
    <Icon>
      <path d="M7 20l5-5 5 5M7 4l5 5 5-5" />
    </Icon>
  );
}

/** The square, bordered button every icon in the header sits in. */
export const iconButton =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-md border border-border-strong px-1.5 text-muted hover:bg-surface-2 hover:text-text";

/**
 * A quieter square for an icon repeated down a list, one per row: no border of its own, so a
 * list of them doesn't read as a column of boxes. The focus ring still outlines it.
 */
export const quietIconButton =
  "inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-text";

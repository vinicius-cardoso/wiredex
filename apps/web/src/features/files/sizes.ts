/**
 * A byte count as a person reads it: `840 B`, `1.2 MB`, `24.0 MB`. The number is localized,
 * so a Brazilian sees `1,2 MB`, and the unit stays the SI-flavoured `KB`/`MB` a file manager
 * shows rather than the exact `KiB`/`MiB`. Steps of 1024 match how the store counts a file.
 */
const UNITS = ["B", "KB", "MB", "GB"] as const;
const STEP = 1024;

export function formatSize(bytes: number, locale: string): string {
  // A negative or non-finite count is nonsense to a reader; show a plain zero rather than
  // "NaN B", so a bad value never leaks into the page.
  if (!Number.isFinite(bytes) || bytes < 0) return format(0, "B", locale);

  let value = bytes;
  let unit = 0;
  while (value >= STEP && unit < UNITS.length - 1) {
    value /= STEP;
    unit += 1;
  }
  // Bytes are whole; everything above shows one decimal, so 1.2 MB never reads as 1 MB.
  return format(value, UNITS[unit] as (typeof UNITS)[number], locale, unit === 0 ? 0 : 1);
}

function format(value: number, unit: (typeof UNITS)[number], locale: string, digits = 0): string {
  const number = new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
  return `${number} ${unit}`;
}

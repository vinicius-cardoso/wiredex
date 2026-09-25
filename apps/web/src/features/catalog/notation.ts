/**
 * Engineering notation, the browser's half of it.
 *
 * The API owns the stored value: it parses what was typed with `Decimal`, exactly, and
 * answers with both the value and its display form. This module exists so the field can
 * show `4.7k` under `4k7` while it is being typed, before anything is sent, and so an
 * unreadable number is caught without a round trip (requirements 7.3, 7.4). It follows the
 * same rules as `catalog/domain/notation.py`; a double is good enough for a preview at four
 * significant digits, and is never what gets stored.
 */

// Case matters: m is milli, M is mega. R is the resistor convention for "no prefix" (1R5
// is 1.5) and u the ASCII spelling of µ. K is absent on purpose: k is kilo, K is kelvin.
const EXPONENT_BY_PREFIX: Record<string, number> = {
  p: -12,
  n: -9,
  µ: -6, // U+00B5 MICRO SIGN, which NFKC folds into the Greek mu below
  μ: -6,
  u: -6,
  m: -3,
  R: 0,
  k: 3,
  M: 6,
  G: 9,
  T: 12,
};

const PREFIX_BY_EXPONENT: Record<number, string> = {
  "-12": "p",
  "-9": "n",
  "-6": "µ",
  "-3": "m",
  0: "",
  3: "k",
  6: "M",
  9: "G",
  12: "T",
};

const MIN_PREFIX_EXPONENT = -12;
const MAX_PREFIX_EXPONENT = 12;
const SIGNIFICANT_DIGITS = 4;

const PREFIXES = Object.keys(EXPONENT_BY_PREFIX).join("");
const DECIMAL = String.raw`[+-]?(?:\d+(?:\.\d+)?|\.\d+)`;
// 4700, 4.7e3
const PLAIN = new RegExp(`^${DECIMAL}(?:[eE][+-]?\\d+)?$`);
// 10k, 100n, 2.2µ
const SUFFIXED = new RegExp(`^(${DECIMAL})([${PREFIXES}])$`);
// 4k7, 2u2, 1R5: the prefix stands in for the decimal point
const INFIXED = new RegExp(`^([+-]?\\d+)([${PREFIXES}])(\\d+)$`);

/**
 * What was typed, in SI base units, or null when it can't be read. A trailing unit is
 * accepted only when it is the attribute's own, so `100nF` is a farad and `100nH` is not.
 */
export function parseSi(text: string, unit?: string | null): number | null {
  const cleaned = text.normalize("NFKC").trim();
  // The prefix reading goes first, so "10m" stays milli even on a metre attribute.
  const direct = read(cleaned);
  if (direct !== null) return direct;
  const bare = withoutUnit(cleaned, unit);
  return bare === null ? null : read(bare);
}

/** The value with the prefix that puts the mantissa in [1, 1000), four digits at most. */
export function formatSi(value: number, unit?: string | null): string {
  const symbol = unit ?? "";
  if (!Number.isFinite(value)) return "";
  if (value === 0) return `0${symbol}`;
  const exponent = engineeringExponent(value);
  const mantissa = Number((value / 10 ** exponent).toPrecision(SIGNIFICANT_DIGITS));
  return `${mantissa}${PREFIX_BY_EXPONENT[exponent] ?? ""}${symbol}`;
}

function read(text: string): number | null {
  if (PLAIN.test(text)) return finite(Number(text));
  const suffixed = SUFFIXED.exec(text);
  if (suffixed) return scaled(suffixed[1], suffixed[2]);
  const infixed = INFIXED.exec(text);
  if (infixed) return scaled(`${infixed[1]}.${infixed[3]}`, infixed[2]);
  return null;
}

/** Scaling through the exponent notation rather than a multiplication, which would drift. */
function scaled(mantissa: string | undefined, prefix: string | undefined): number | null {
  const exponent = prefix === undefined ? undefined : EXPONENT_BY_PREFIX[prefix];
  if (mantissa === undefined || exponent === undefined) return null;
  return finite(Number(`${mantissa}e${exponent}`));
}

function withoutUnit(text: string, unit: string | null | undefined): string | null {
  if (!unit) return null;
  const symbol = unit.normalize("NFKC");
  if (!text.endsWith(symbol) || text.length === symbol.length) return null;
  return text.slice(0, -symbol.length);
}

function finite(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

/**
 * The multiple of three to divide by. Rounding to four digits happens first, so 999.99
 * becomes 1k rather than 1000.
 */
function engineeringExponent(value: number): number {
  const rounded = Math.abs(value).toExponential(SIGNIFICANT_DIGITS - 1);
  const decades = Number(rounded.slice(rounded.indexOf("e") + 1));
  const multipleOfThree = Math.floor(decades / 3) * 3;
  return Math.min(MAX_PREFIX_EXPONENT, Math.max(MIN_PREFIX_EXPONENT, multipleOfThree));
}

import type { FilterRequest, PartSearchRequest } from "@wiredex/api-client";

/**
 * The search, as it lives in the page's address (requirement 6.4).
 *
 * TanStack Router keeps whatever `validateSearch` returns in the URL, so a search can be
 * bookmarked, shared, and walked with Back and Forward. This module is the one translation
 * between three shapes: the raw params a URL carries (anything, including a hand-edited
 * mess), the `PartQuery` the page works with, and the `PartSearchRequest` body the API
 * reads. Garbage in the address is dropped, never thrown: a half-broken link still opens a
 * usable page rather than an error (requirement 6.4).
 */

export type SortField = "newest" | "name" | { attribute: string };
export type SortDirection = "asc" | "desc";

/** One filter as the page holds it: a discriminated union mirroring the API's shapes. */
export type PartFilter =
  | { type: "range"; key: string; minimum: string | null; maximum: string | null }
  | { type: "options"; key: string; options: string[] }
  | { type: "bool"; key: string; value: boolean }
  | { type: "text"; key: string; text: string };

/** The whole search the page reads and writes; every field has a sensible default. */
export type PartQuery = {
  text: string;
  category: string | null;
  exact: boolean;
  pin: string;
  filters: PartFilter[];
  sort: SortField;
  direction: SortDirection;
};

export const emptyQuery: PartQuery = {
  text: "",
  category: null,
  exact: false,
  pin: "",
  filters: [],
  sort: "newest",
  direction: "desc",
};

/**
 * The address, parsed. TanStack calls this with whatever the URL held; anything that doesn't
 * fit falls back to its default, so `?sort=chaos&exact=maybe&f=nonsense` opens the plain
 * list instead of throwing (requirement 6.4). Only the fields that differ from the defaults
 * are returned, which keeps a plain `/parts` address empty.
 */
export function validateSearch(raw: Record<string, unknown>): PartSearchParams {
  const params: PartSearchParams = {};
  const text = trimmedString(raw.text);
  if (text) params.text = text;

  const category = trimmedString(raw.category);
  if (category) {
    params.category = category;
    // "only this category" means nothing without a category, so it rides with one.
    if (raw.exact === true || raw.exact === "true") params.exact = true;
  }

  const pin = trimmedString(raw.pin);
  if (pin) params.pin = pin;

  const filters = parseFilters(raw.f);
  if (filters.length > 0) params.f = filters;

  const sort = parseSort(raw.sort);
  if (sort !== "newest") params.sort = encodeSort(sort);

  if (raw.dir === "asc") params.dir = "asc";

  return params;
}

/**
 * What lands in the URL: the compact form, with every default left out so a plain search is
 * a plain `/parts`. `f` is the encoded filters, `sort` and `dir` the ordering.
 */
export type PartSearchParams = {
  text?: string;
  category?: string;
  exact?: true;
  pin?: string;
  f?: string[];
  sort?: string;
  dir?: "asc";
};

/** The address turned into the search the page works with, defaults filled in. */
export function queryFromParams(params: PartSearchParams): PartQuery {
  return {
    text: params.text ?? "",
    category: params.category ?? null,
    exact: params.exact === true && params.category !== undefined,
    pin: params.pin ?? "",
    filters: (params.f ?? [])
      .map(decodeFilter)
      .filter((filter): filter is PartFilter => filter !== null),
    sort: parseSort(params.sort),
    direction: params.dir === "asc" ? "asc" : "desc",
  };
}

/** The search the page works with, encoded back into the compact address form. */
export function paramsFromQuery(query: PartQuery): PartSearchParams {
  const params: PartSearchParams = {};
  const text = query.text.trim();
  if (text) params.text = text;
  if (query.category) {
    params.category = query.category;
    if (query.exact) params.exact = true;
  }
  const pin = query.pin.trim();
  if (pin) params.pin = pin;
  const encoded = query.filters
    .map(encodeFilter)
    .filter((value): value is string => value !== null);
  if (encoded.length > 0) params.f = encoded;
  if (query.sort !== "newest") params.sort = encodeSort(query.sort);
  if (query.direction === "asc") params.dir = "asc";
  return params;
}

/**
 * The search as the API reads it. Attribute filters without a category are dropped here as
 * well as refused there: only a category's schema says what a key means (requirement 2.8),
 * so sending them would only earn a 422.
 */
export function requestFromQuery(query: PartQuery): PartSearchRequest {
  const hasCategory = query.category !== null;
  const filters = hasCategory
    ? query.filters
        .map(toFilterRequest)
        .filter((filter): filter is FilterRequest => filter !== null)
    : [];
  return {
    text: query.text.trim() || null,
    category_id: query.category,
    exact_category: hasCategory && query.exact,
    pin: query.pin.trim() || null,
    filters,
    sort: encodeSort(query.sort),
    direction: query.direction,
    limit: 50,
  };
}

// --- sort ---------------------------------------------------------------------------------

function parseSort(raw: unknown): SortField {
  if (raw === "name") return "name";
  if (typeof raw === "string" && raw.startsWith("attribute:")) {
    const key = raw.slice("attribute:".length);
    if (key) return { attribute: key };
  }
  return "newest";
}

function encodeSort(sort: SortField): string {
  if (sort === "newest" || sort === "name") return sort;
  return `attribute:${sort.attribute}`;
}

// --- filters ------------------------------------------------------------------------------

/** Only strings survive as filter tokens; anything else in `f` is dropped, not thrown. */
function parseFilters(raw: unknown): string[] {
  const tokens = Array.isArray(raw) ? raw : typeof raw === "string" ? [raw] : [];
  return tokens.filter(
    (token): token is string => typeof token === "string" && decodeFilter(token) !== null,
  );
}

/**
 * One filter, encoded compactly: a one-letter kind, the key, then the kind's own payload,
 * each part `encodeURIComponent`d so a `:` or `|` inside an option or a fragment can't split
 * the token. `r` range, `o` options, `b` bool, `t` text.
 */
export function encodeFilter(filter: PartFilter): string | null {
  const key = encodeURIComponent(filter.key);
  switch (filter.type) {
    case "range": {
      if (filter.minimum === null && filter.maximum === null) return null;
      return `r:${key}:${part(filter.minimum)}:${part(filter.maximum)}`;
    }
    case "options": {
      if (filter.options.length === 0) return null;
      return `o:${key}:${filter.options.map((option) => encodeURIComponent(option)).join("|")}`;
    }
    case "bool":
      return `b:${key}:${filter.value ? "1" : "0"}`;
    case "text": {
      if (filter.text.trim() === "") return null;
      return `t:${key}:${encodeURIComponent(filter.text)}`;
    }
  }
}

/** A filter token back into a filter, or null when it's malformed (requirement 6.4). */
export function decodeFilter(token: string): PartFilter | null {
  const sigil = token[0];
  if (token[1] !== ":") return null;
  const rest = token.slice(2);
  switch (sigil) {
    case "r": {
      const segments = rest.split(":");
      if (segments.length !== 3) return null;
      const key = decode(segments[0]);
      const minimum = unpart(segments[1]);
      const maximum = unpart(segments[2]);
      if (key === null) return null;
      if (minimum === null && maximum === null) return null;
      return { type: "range", key, minimum, maximum };
    }
    case "o": {
      const cut = rest.indexOf(":");
      if (cut === -1) return null;
      const key = decode(rest.slice(0, cut));
      const payload = rest.slice(cut + 1);
      if (key === null || payload === "") return null;
      const options = payload.split("|").map(decode);
      if (options.some((option) => option === null)) return null;
      return { type: "options", key, options: options as string[] };
    }
    case "b": {
      const cut = rest.indexOf(":");
      if (cut === -1) return null;
      const key = decode(rest.slice(0, cut));
      const value = rest.slice(cut + 1);
      if (key === null || (value !== "0" && value !== "1")) return null;
      return { type: "bool", key, value: value === "1" };
    }
    case "t": {
      const cut = rest.indexOf(":");
      if (cut === -1) return null;
      const key = decode(rest.slice(0, cut));
      const text = decode(rest.slice(cut + 1));
      if (key === null || !text || text.trim() === "") return null;
      return { type: "text", key, text };
    }
    default:
      return null;
  }
}

function toFilterRequest(filter: PartFilter): FilterRequest | null {
  switch (filter.type) {
    case "range":
      if (filter.minimum === null && filter.maximum === null) return null;
      return { type: "range", key: filter.key, minimum: filter.minimum, maximum: filter.maximum };
    case "options":
      if (filter.options.length === 0) return null;
      return { type: "options", key: filter.key, options: filter.options };
    case "bool":
      return { type: "bool", key: filter.key, value: filter.value };
    case "text":
      if (filter.text.trim() === "") return null;
      return { type: "text", key: filter.key, text: filter.text };
  }
}

/** An empty bound is `-` in the token, so `r:key::4k7` can't be mistaken for a two-part one. */
function part(value: string | null): string {
  return value === null || value === "" ? "-" : encodeURIComponent(value);
}

function unpart(segment: string | undefined): string | null {
  if (segment === undefined || segment === "-" || segment === "") return null;
  return decode(segment);
}

/** `decodeURIComponent` throws on a malformed escape; a broken token is dropped, not fatal. */
function decode(segment: string | undefined): string | null {
  if (segment === undefined) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

function trimmedString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

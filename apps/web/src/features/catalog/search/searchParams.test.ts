import { describe, expect, it } from "vitest";
import type { PartFilter, PartQuery } from "./searchParams";
import {
  decodeFilter,
  emptyQuery,
  encodeFilter,
  narrows,
  paramsFromQuery,
  queryFromParams,
  requestFromQuery,
  validateSearch,
} from "./searchParams";

/** A search through the address and back: what goes in must come out unchanged. */
function roundTrip(query: PartQuery): PartQuery {
  const params = paramsFromQuery(query);
  return queryFromParams(validateSearch(params as Record<string, unknown>));
}

const CATEGORY = "0199aaaa-0000-7000-8000-000000000001";

describe("the search round-trips through the address", () => {
  it("keeps a plain search plain", () => {
    expect(roundTrip(emptyQuery)).toEqual(emptyQuery);
    expect(paramsFromQuery(emptyQuery)).toEqual({});
  });

  it("keeps the text, trimmed", () => {
    const query = { ...emptyQuery, text: "  ATmega  " };
    expect(roundTrip(query).text).toBe("ATmega");
  });

  it("keeps a category and its 'only this one' flag", () => {
    const query = { ...emptyQuery, category: CATEGORY, exact: true };
    expect(roundTrip(query)).toMatchObject({ category: CATEGORY, exact: true });
  });

  it("drops 'only this category' when there is no category", () => {
    const query = { ...emptyQuery, exact: true };
    expect(roundTrip(query).exact).toBe(false);
    expect(paramsFromQuery(query).exact).toBeUndefined();
  });

  it("keeps the pin, trimmed", () => {
    const query = { ...emptyQuery, pin: " SDA " };
    expect(roundTrip(query).pin).toBe("SDA");
  });

  it("keeps the manufacturer, trimmed, and the stock", () => {
    const query: PartQuery = { ...emptyQuery, manufacturer: " Yageo ", stock: "out_of_stock" };
    expect(paramsFromQuery(query)).toEqual({ manufacturer: "Yageo", stock: "out_of_stock" });
    expect(roundTrip(query)).toMatchObject({ manufacturer: "Yageo", stock: "out_of_stock" });
  });

  it("drops a stock filter it doesn't know", () => {
    expect(validateSearch({ stock: "plenty" })).toEqual({});
  });

  it.each<PartFilter>([
    { type: "range", key: "resistance", minimum: "1k", maximum: "10k" },
    { type: "range", key: "resistance", minimum: "1k", maximum: null },
    { type: "range", key: "resistance", minimum: null, maximum: "10k" },
    { type: "options", key: "package", options: ["0805", "0603"] },
    { type: "options", key: "package", options: ["a:b|c", "d"] }, // delimiters inside a value
    { type: "bool", key: "rohs", value: true },
    { type: "bool", key: "rohs", value: false },
    { type: "text", key: "notes", text: "high temp" },
    { type: "text", key: "notes", text: "colon: and | pipe" },
  ])("keeps the %o filter", (filter) => {
    const query = { ...emptyQuery, category: CATEGORY, filters: [filter] };
    expect(roundTrip(query).filters).toEqual([filter]);
  });

  it("keeps several filters together", () => {
    const filters: PartFilter[] = [
      { type: "range", key: "resistance", minimum: "1k", maximum: "10k" },
      { type: "options", key: "package", options: ["0805"] },
      { type: "bool", key: "rohs", value: true },
    ];
    const query = { ...emptyQuery, category: CATEGORY, filters };
    expect(roundTrip(query).filters).toEqual(filters);
  });

  it.each<[PartQuery["sort"], PartQuery["direction"]]>([
    ["newest", "desc"],
    ["newest", "asc"],
    ["name", "asc"],
    ["name", "desc"],
    [{ attribute: "resistance" }, "asc"],
    [{ attribute: "resistance" }, "desc"],
  ])("keeps the %o sort in %s", (sort, direction) => {
    const query = { ...emptyQuery, sort, direction };
    expect(roundTrip(query)).toMatchObject({ sort, direction });
  });
});

describe("the page in the address", () => {
  it("keeps a page and a size beside the search", () => {
    const params = validateSearch({ text: "4k7", page: 3, size: "50" });

    expect(params).toEqual({ text: "4k7", page: 3, size: 50 });
    expect(paramsFromQuery(queryFromParams(params))).toEqual({ text: "4k7" });
  });

  it("drops a page or size that isn't one, and the defaults", () => {
    const params = validateSearch({ page: "abc", size: 7 });

    expect(params).toEqual({});
    // Both keys present, so a raw value in the address never shows through the router.
    expect(Object.keys(validateSearch({ page: 1, size: 25 }))).toEqual(["page", "size"]);
  });
});

describe("garbage in the address is dropped, not thrown", () => {
  it("survives values of the wrong type", () => {
    const params = validateSearch({
      text: 42,
      category: { nope: true },
      exact: "maybe",
      pin: ["array"],
      f: 99,
      sort: 7,
      dir: "sideways",
    });
    expect(queryFromParams(params)).toEqual(emptyQuery);
  });

  it("drops an unknown sort back to newest", () => {
    expect(queryFromParams(validateSearch({ sort: "chaos" }))).toMatchObject({ sort: "newest" });
    expect(queryFromParams(validateSearch({ sort: "attribute:" }))).toMatchObject({
      sort: "newest",
    });
  });

  it("drops malformed filter tokens and keeps the good ones", () => {
    const params = validateSearch({
      f: [
        "r:resistance:1k:10k", // good
        "nonsense", // no sigil separator
        "z:key:1", // unknown kind
        "b:rohs:2", // not a boolean
        "r:resistance:-:-", // a range with no bounds
        "o:package:", // no options
        "t:notes:", // empty text
      ],
    });
    expect(queryFromParams(params).filters).toEqual([
      { type: "range", key: "resistance", minimum: "1k", maximum: "10k" },
    ]);
  });

  it("drops a filter token whose escapes are broken instead of throwing", () => {
    expect(() => validateSearch({ f: ["t:notes:%zz"] })).not.toThrow();
    expect(decodeFilter("t:notes:%zz")).toBeNull();
    expect(queryFromParams(validateSearch({ f: ["t:notes:%zz"] })).filters).toEqual([]);
  });

  it("accepts a single filter string as well as an array", () => {
    const params = validateSearch({ f: "b:rohs:1" });
    expect(queryFromParams(params).filters).toEqual([{ type: "bool", key: "rohs", value: true }]);
  });
});

describe("the request body", () => {
  it("drops attribute filters when no category is chosen", () => {
    const query: PartQuery = {
      ...emptyQuery,
      filters: [{ type: "bool", key: "rohs", value: true }],
    };
    const body = requestFromQuery(query);
    expect(body.category_id).toBeNull();
    expect(body.filters).toEqual([]);
    expect(body.exact_category).toBe(false);
  });

  it("sends the filters when a category is chosen", () => {
    const query: PartQuery = {
      ...emptyQuery,
      category: CATEGORY,
      exact: true,
      text: "  res  ",
      pin: " SDA ",
      filters: [{ type: "range", key: "resistance", minimum: "1k", maximum: null }],
      sort: { attribute: "resistance" },
      direction: "asc",
    };
    expect(requestFromQuery(query)).toEqual({
      text: "res",
      category_id: CATEGORY,
      exact_category: true,
      pin: "SDA",
      manufacturer: null,
      stock: null,
      filters: [{ type: "range", key: "resistance", minimum: "1k", maximum: null }],
      sort: "attribute:resistance",
      direction: "asc",
    });
  });

  it("leaves the page out, which each caller adds", () => {
    const body = requestFromQuery(emptyQuery);

    expect(body).not.toHaveProperty("limit");
    expect(body).not.toHaveProperty("page");
    expect(body).not.toHaveProperty("page_size");
  });

  it("turns empty text and pin into null", () => {
    const body = requestFromQuery({ ...emptyQuery, text: "   ", pin: "" });
    expect(body.text).toBeNull();
    expect(body.pin).toBeNull();
  });

  it("sends the manufacturer, trimmed, and the stock, with or without a category", () => {
    const body = requestFromQuery({ ...emptyQuery, manufacturer: " Yageo ", stock: "in_stock" });
    expect(body.manufacturer).toBe("Yageo");
    expect(body.stock).toBe("in_stock");
    expect(requestFromQuery({ ...emptyQuery, manufacturer: "  " }).manufacturer).toBeNull();
  });
});

describe("what narrows the list", () => {
  it("is nothing in a plain search, whatever its sort", () => {
    expect(narrows(emptyQuery)).toBe(false);
    expect(narrows({ ...emptyQuery, sort: "name", direction: "asc" })).toBe(false);
  });

  it.each<Partial<PartQuery>>([
    { text: "res" },
    { category: CATEGORY },
    { pin: "SDA" },
    { manufacturer: "Yageo" },
    { stock: "out_of_stock" },
    { filters: [{ type: "bool", key: "rohs", value: true }] },
  ])("is any filter: %o", (filter) => {
    expect(narrows({ ...emptyQuery, ...filter })).toBe(true);
  });
});

describe("encodeFilter refuses empty filters", () => {
  it("returns null for a range with no bounds and empty options and blank text", () => {
    expect(encodeFilter({ type: "range", key: "r", minimum: null, maximum: null })).toBeNull();
    expect(encodeFilter({ type: "options", key: "p", options: [] })).toBeNull();
    expect(encodeFilter({ type: "text", key: "n", text: "  " })).toBeNull();
  });
});

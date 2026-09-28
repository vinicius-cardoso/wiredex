import type {
  AdjustRequest,
  AttachmentResponse,
  AttributeChange,
  BalanceResponse,
  CategoryChange,
  CategoryNode,
  CellProblem,
  ChangeAttachmentRequest,
  FacetsResponse,
  FilterRequest,
  ImportPreview,
  ImportRequest,
  ImportResult,
  ImportRow,
  ImportSheetRequest,
  ImportSummary,
  LocationChange,
  LocationNode,
  MoveRequest,
  MoveResponse,
  NewAttribute,
  NewCategory,
  NewLocation,
  NewPart,
  PartDetails,
  PartRevision,
  PartSearchRequest,
  PartStock,
  PartSummary,
  PartTotal,
  Pin,
  PinoutReplacement,
  QuickAddRequest,
  QuickAddResponse,
  ReceiveRequest,
  ReceiveUnitsRequest,
  RelabelUnitRequest,
  SchemaAttribute,
  SearchResult,
  SessionInfo,
  UnitResponse,
} from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer();

export function respondWithApiVersion(version: string, commit = "0123456789abcdef") {
  server.use(
    http.get("*/api/version", () => HttpResponse.json({ version, commit, built_at: null })),
  );
}

export function failApiVersion() {
  server.use(http.get("*/api/version", () => HttpResponse.error()));
}

export const OWNER = {
  id: "0199aaaa-0000-7000-8000-000000000001",
  email: "owner@example.com",
  name: "Owner",
  expires_at: null as string | null,
};

export function respondAsLoggedIn(user = OWNER) {
  server.use(http.get("*/api/auth/me", () => HttpResponse.json(user)));
}

export function respondAsLoggedOut() {
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json({ detail: "log in first" }, { status: 401 })),
  );
}

/** Accepts OWNER's email with the password "correct horse battery". */
export function acceptLogins({ status = 200 } = {}) {
  server.use(
    http.post("*/api/auth/login", async ({ request }) => {
      const body = (await request.json()) as { email: string; password: string };
      const valid = body.email === OWNER.email && body.password === "correct horse battery";
      if (status !== 200) return HttpResponse.json({ detail: "refused" }, { status });
      if (!valid) return HttpResponse.json({ detail: "wrong email or password" }, { status: 401 });
      respondAsLoggedIn();
      return HttpResponse.json(OWNER);
    }),
  );
}

export function acceptLogout() {
  server.use(
    http.post("*/api/auth/logout", () => {
      respondAsLoggedOut();
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

export const FIREFOX_ON_LINUX =
  "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0";

export function aSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    id: "0199aaaa-0000-7000-8000-0000000000a1",
    device: FIREFOX_ON_LINUX,
    created_at: "2026-09-20T10:00:00Z",
    last_seen_at: "2026-09-24T12:00:00Z",
    current: true,
    ...overrides,
  };
}

/** Lists SESSIONS and deletes from it, like the real API. */
export function respondWithSessions(sessions: SessionInfo[]) {
  let remaining = [...sessions];
  server.use(
    http.get("*/api/auth/sessions", () => HttpResponse.json(remaining)),
    http.delete("*/api/auth/sessions/:id", ({ params }) => {
      remaining = remaining.filter((session) => session.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

export function aCategory(overrides: Partial<CategoryNode> = {}): CategoryNode {
  return {
    id: "0199bbbb-0000-7000-8000-000000000001",
    parent_id: null,
    name: "Passives",
    created_at: "2026-09-20T10:00:00Z",
    child_count: 0,
    part_count: 0,
    tracked_individually: null,
    tracked_individually_resolved: false,
    ...overrides,
  };
}

export function aPart(overrides: Partial<PartSummary> = {}): PartSummary {
  return {
    id: "0199cccc-0000-7000-8000-000000000001",
    category_id: aCategory().id,
    name: "4.7 kΩ 1% 0805",
    manufacturer: "Yageo",
    mpn: "RC0805FR-074K7L",
    package: "0805",
    created_at: "2026-09-21T09:00:00Z",
    updated_at: "2026-09-21T09:00:00Z",
    ...overrides,
  };
}

export function respondWithCategories(categories: CategoryNode[]) {
  server.use(http.get("*/api/catalog/categories", () => HttpResponse.json(categories)));
}

/**
 * Pages PARTS the way the API does: `q` is a substring of the name, `category_id` an exact
 * match, and the cursor is the last id of the previous window, so the next one starts after it.
 */
export function respondWithParts(parts: PartSummary[]) {
  server.use(
    http.get("*/api/catalog/parts", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const search = params.get("q")?.toLowerCase();
      const categoryId = params.get("category_id");
      // The API's own default page size, so a test that doesn't ask for one pages alike.
      const limit = Number(params.get("limit") ?? 50);
      const cursor = params.get("cursor");

      let matching = parts;
      if (search) matching = matching.filter((part) => part.name.toLowerCase().includes(search));
      if (categoryId) matching = matching.filter((part) => part.category_id === categoryId);
      const from = cursor ? matching.findIndex((part) => part.id === cursor) + 1 : 0;
      const items = matching.slice(from, from + limit);
      const more = matching.length > from + items.length;
      return HttpResponse.json({
        items,
        next_cursor: more && items.length > 0 ? items[items.length - 1]?.id : null,
      });
    }),
  );
}

export function aSearchResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    ...aPart(),
    attributes: {},
    ...overrides,
  };
}

/**
 * Searches RESULTS the way the API does, enough for the web to be tested: `text` is a
 * case-insensitive substring of name, manufacturer or part number; `category_id` an exact
 * match; each attribute filter narrows on the result's own `attributes`; `sort` and
 * `direction` order the page, and the cursor is the last id of the previous window. The
 * array holds every request body sent, so a test can assert what the page asked for.
 */
export function respondWithSearch(results: SearchResult[]): PartSearchRequest[] {
  const sent: PartSearchRequest[] = [];
  server.use(
    http.post("*/api/catalog/parts/search", async ({ request }) => {
      const body = (await request.json()) as PartSearchRequest;
      sent.push(body);

      let matching = results;
      const text = body.text?.toLowerCase();
      if (text) {
        matching = matching.filter((part) =>
          [part.name, part.manufacturer, part.mpn, part.package]
            .filter((field): field is string => field != null)
            .some((field) => field.toLowerCase().includes(text)),
        );
      }
      if (body.category_id) {
        matching = matching.filter((part) => part.category_id === body.category_id);
      }
      for (const filter of body.filters ?? []) {
        matching = matching.filter((part) => passesFilter(part, filter));
      }
      matching = sortResults(matching, body.sort, body.direction);

      const limit = body.limit ?? 50;
      const cursor = body.cursor ?? null;
      const from = cursor ? matching.findIndex((part) => part.id === cursor) + 1 : 0;
      const items = matching.slice(from, from + limit);
      const more = matching.length > from + items.length;
      return HttpResponse.json({
        items,
        next_cursor: more && items.length > 0 ? items[items.length - 1]?.id : null,
      });
    }),
  );
  return sent;
}

function passesFilter(part: SearchResult, filter: FilterRequest): boolean {
  const value = part.attributes[filter.key];
  switch (filter.type) {
    case "range": {
      if (value === undefined || typeof value.value !== "string") return false;
      const held = Number(value.value);
      const min = filter.minimum == null ? null : Number(filter.minimum);
      const max = filter.maximum == null ? null : Number(filter.maximum);
      if (min !== null && held < min) return false;
      if (max !== null && held > max) return false;
      return true;
    }
    case "options":
      return value !== undefined && (filter.options ?? []).includes(String(value.value));
    case "bool":
      return value !== undefined && value.value === filter.value;
    case "text":
      return (
        value !== undefined &&
        typeof value.value === "string" &&
        value.value.toLowerCase().includes((filter.text ?? "").toLowerCase())
      );
  }
}

function sortResults(results: SearchResult[], sort: string, direction: string): SearchResult[] {
  // "newest" keeps the order given, the way the API answers a default search; only an
  // explicit sort reorders, and the direction flips that comparison.
  if (sort !== "name" && !sort.startsWith("attribute:")) return results;
  const sorted = [...results];
  if (sort === "name") {
    sorted.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    const key = sort.slice("attribute:".length);
    sorted.sort(
      (a, b) => Number(a.attributes[key]?.value ?? 0) - Number(b.attributes[key]?.value ?? 0),
    );
  }
  return direction === "asc" ? sorted : sorted.reverse();
}

/** Refuses a search the way the API does when it names a filter it can't read (6.5). */
export function refuseSearch(detail: string, status = 422) {
  server.use(
    http.post("*/api/catalog/parts/search", () => HttpResponse.json({ detail }, { status })),
  );
}

/** A category's facets, keyed by attribute, the way the API answers (requirement 5.1). */
export function respondWithFacets(category: CategoryNode, facets: FacetsResponse) {
  server.use(
    http.get("*/api/catalog/categories/:categoryId/facets", ({ params }) => {
      if (params.categoryId !== category.id) return notFound("that category doesn't exist");
      return HttpResponse.json(facets);
    }),
  );
}

export function anAttribute(overrides: Partial<SchemaAttribute> = {}): SchemaAttribute {
  return {
    id: "0199dddd-0000-7000-8000-000000000001",
    category_id: aCategory().id,
    key: "resistance",
    label: "Resistance",
    kind: "number",
    unit: "Ω",
    required: true,
    options: [],
    position: 0,
    inherited: false,
    ...overrides,
  };
}

export function aPartDetails(overrides: Partial<PartDetails> = {}): PartDetails {
  // `pin_count: 0` is the part most tests want: one with no pin table, which is what a part
  // is until someone enters one. A test about a pinout overrides it.
  return {
    ...aPart(),
    attributes: {},
    needs_review: false,
    problems: [],
    pin_count: 0,
    ...overrides,
  };
}

/** The resolved schema of one category; any other id is a 404, as the API answers. */
export function respondWithCategorySchema(category: CategoryNode, attributes: SchemaAttribute[]) {
  respondWithCategorySchemas([{ category, attributes }]);
}

/** The resolved schemas of several categories at once; any other id is a 404. */
export function respondWithCategorySchemas(
  schemas: { category: CategoryNode; attributes: SchemaAttribute[] }[],
) {
  server.use(
    http.get("*/api/catalog/categories/:categoryId/schema", ({ params }) => {
      const found = schemas.find(({ category }) => category.id === params.categoryId);
      if (!found) return notFound("that category doesn't exist");
      const { category, attributes } = found;
      return HttpResponse.json({
        category: {
          id: category.id,
          parent_id: category.parent_id,
          name: category.name,
          created_at: category.created_at,
          tracked_individually: category.tracked_individually,
          tracked_individually_resolved: category.tracked_individually_resolved,
        },
        attributes,
      });
    }),
  );
}

export function respondWithPart(part: PartDetails) {
  server.use(
    http.get("*/api/catalog/parts/:partId", ({ params }) =>
      params.partId === part.id ? HttpResponse.json(part) : notFound("that part doesn't exist"),
    ),
  );
}

/** Takes what the form sends and answers with `saved`. The array holds every body sent. */
export function acceptPartSaves(saved: PartDetails = aPartDetails()): (NewPart | PartRevision)[] {
  const sent: (NewPart | PartRevision)[] = [];
  server.use(
    http.post("*/api/catalog/parts", async ({ request }) => {
      sent.push((await request.json()) as NewPart);
      return HttpResponse.json(saved, { status: 201 });
    }),
    http.patch("*/api/catalog/parts/:partId", async ({ request }) => {
      sent.push((await request.json()) as PartRevision);
      return HttpResponse.json(saved);
    }),
  );
  return sent;
}

export function aPin(overrides: Partial<Pin> = {}): Pin {
  return {
    number: "1",
    label: "GND",
    type: "ground",
    functions: [],
    voltage: null,
    ...overrides,
  };
}

/** The pins of one part, in the order given; any other part has none, as the API answers. */
export function respondWithPinout(partId: string, pins: Pin[]) {
  server.use(
    http.get("*/api/catalog/parts/:partId/pinout", ({ params }) =>
      HttpResponse.json({ pins: params.partId === partId ? pins : [] }),
    ),
  );
}

/** Takes a whole table and answers with `saved`. The array holds every body sent. */
export function acceptPinoutSaves(saved: Pin[] = [aPin()]): PinoutReplacement[] {
  const sent: PinoutReplacement[] = [];
  server.use(
    http.put("*/api/catalog/parts/:partId/pinout", async ({ request }) => {
      sent.push((await request.json()) as PinoutReplacement);
      return HttpResponse.json({ pins: saved });
    }),
  );
  return sent;
}

/**
 * Refuses a table the way the API does: the row and the cell as data, both null when the
 * whole table is refused (requirements 3.1 to 3.3).
 */
export function refusePinoutSaves(
  message: string,
  { row = null, field = null }: { row?: number | null; field?: string | null } = {},
) {
  server.use(
    http.put("*/api/catalog/parts/:partId/pinout", () =>
      HttpResponse.json({ detail: { message, row, field } }, { status: 422 }),
    ),
  );
}

/** Refuses a save the way the API does: a status and a message naming what went wrong. */
export function refusePartSaves(detail: string, status = 422) {
  server.use(
    http.post("*/api/catalog/parts", () => HttpResponse.json({ detail }, { status })),
    http.patch("*/api/catalog/parts/:partId", () => HttpResponse.json({ detail }, { status })),
  );
}

export function acceptPartDeletion() {
  server.use(
    http.delete("*/api/catalog/parts/:partId", () => new HttpResponse(null, { status: 204 })),
  );
}

export function anAttachment(overrides: Partial<AttachmentResponse> = {}): AttachmentResponse {
  const id = overrides.id ?? "0199eeee-0000-7000-8000-000000000001";
  return {
    id,
    subject: "part:0199cccc-0000-7000-8000-000000000001",
    kind: "datasheet",
    title: "Datasheet",
    media_type: "application/pdf",
    size: 1_258_291,
    created_at: "2026-09-25T10:00:00Z",
    content_url: `/api/files/attachments/${id}/content`,
    ...overrides,
  };
}

/**
 * Lists ATTACHMENTS for the matching subject and deletes from that list, the way the API
 * does: removing one and listing again shows it gone. Any other subject has none.
 */
export function respondWithAttachments(subject: string, attachments: AttachmentResponse[]) {
  let remaining = [...attachments];
  server.use(
    http.get("*/api/files/attachments", ({ request }) => {
      const asked = new URL(request.url).searchParams.get("subject");
      return HttpResponse.json(asked === subject ? remaining : []);
    }),
    http.delete("*/api/files/attachments/:attachmentId", ({ params }) => {
      remaining = remaining.filter((attachment) => attachment.id !== params.attachmentId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

/**
 * Takes a multipart upload and answers 201 with `saved`, echoing the chosen kind the way the
 * API does. The array holds the `{ subject, kind, title, hasFile }` of every upload sent, so
 * a test can check the DropZone posted the right kind with a file attached.
 */
export function acceptUploads(saved: AttachmentResponse = anAttachment()): {
  subject: string | null;
  kind: string;
  title: string | null;
  hasFile: boolean;
}[] {
  const sent: { subject: string | null; kind: string; title: string | null; hasFile: boolean }[] =
    [];
  server.use(
    http.post("*/api/files/attachments", async ({ request }) => {
      const form = await request.formData();
      sent.push({
        subject: form.get("subject") as string | null,
        kind: String(form.get("kind")),
        title: form.get("title") as string | null,
        hasFile: form.get("file") != null,
      });
      return HttpResponse.json({ ...saved, kind: form.get("kind") as never }, { status: 201 });
    }),
  );
  return sent;
}

/** Refuses an upload the way the API does: a status and a message (requirement 6.3). */
export function refuseUploads(detail: string, status: number) {
  server.use(http.post("*/api/files/attachments", () => HttpResponse.json({ detail }, { status })));
}

/** Takes a change and answers with `saved`. The array holds every body sent. */
export function acceptAttachmentChanges(
  saved: AttachmentResponse = anAttachment(),
): ChangeAttachmentRequest[] {
  const sent: ChangeAttachmentRequest[] = [];
  server.use(
    http.patch("*/api/files/attachments/:attachmentId", async ({ request }) => {
      sent.push((await request.json()) as ChangeAttachmentRequest);
      return HttpResponse.json(saved);
    }),
  );
  return sent;
}

/** Refuses a change the way the API does: a status and a message. */
export function refuseAttachmentChanges(detail: string, status = 422) {
  server.use(
    http.patch("*/api/files/attachments/:attachmentId", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

/** Refuses a removal the way the API does when the store can't be reached (503). */
export function refuseAttachmentRemoval(detail: string, status = 503) {
  server.use(
    http.delete("*/api/files/attachments/:attachmentId", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

function notFound(detail: string) {
  return HttpResponse.json({ detail }, { status: 404 });
}

/** Takes a new category and answers with it, as the API does. Holds every body sent. */
export function acceptNewCategories(created: CategoryNode = aCategory()): NewCategory[] {
  const sent: NewCategory[] = [];
  server.use(
    http.post("*/api/catalog/categories", async ({ request }) => {
      sent.push((await request.json()) as NewCategory);
      return HttpResponse.json(
        {
          id: created.id,
          parent_id: created.parent_id,
          name: created.name,
          created_at: created.created_at,
        },
        { status: 201 },
      );
    }),
  );
  return sent;
}

export function acceptCategoryEdits(edited: CategoryNode = aCategory()): CategoryChange[] {
  const sent: CategoryChange[] = [];
  server.use(
    http.patch("*/api/catalog/categories/:categoryId", async ({ request }) => {
      const body = (await request.json()) as CategoryChange;
      sent.push(body);
      // Echo the tracking flag the way the API answers it: what the body set, or the
      // category's own value when the patch left it out (design's category PATCH).
      const tracked =
        "tracked_individually" in body ? body.tracked_individually : edited.tracked_individually;
      return HttpResponse.json({
        id: edited.id,
        parent_id: edited.parent_id,
        name: edited.name,
        created_at: edited.created_at,
        tracked_individually: tracked ?? null,
        tracked_individually_resolved: tracked ?? edited.tracked_individually_resolved,
      });
    }),
  );
  return sent;
}

export function acceptCategoryDeletion() {
  server.use(
    http.delete(
      "*/api/catalog/categories/:categoryId",
      () => new HttpResponse(null, { status: 204 }),
    ),
  );
}

/** Refuses a delete the way the API refuses one still in use (requirement 1.9). */
export function refuseCategoryDeletion(detail: string, status = 409) {
  server.use(
    http.delete("*/api/catalog/categories/:categoryId", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

export function acceptNewAttributes(defined: SchemaAttribute = anAttribute()): NewAttribute[] {
  const sent: NewAttribute[] = [];
  server.use(
    http.post("*/api/catalog/categories/:categoryId/attributes", async ({ request }) => {
      sent.push((await request.json()) as NewAttribute);
      const { inherited, ...attribute } = defined;
      return HttpResponse.json(attribute, { status: 201 });
    }),
  );
  return sent;
}

export function acceptAttributeEdits(edited: SchemaAttribute = anAttribute()): AttributeChange[] {
  const sent: AttributeChange[] = [];
  server.use(
    http.patch("*/api/catalog/attributes/:attributeId", async ({ request }) => {
      sent.push((await request.json()) as AttributeChange);
      const { inherited, ...attribute } = edited;
      return HttpResponse.json(attribute);
    }),
  );
  return sent;
}

export function acceptAttributeRemoval() {
  server.use(
    http.delete(
      "*/api/catalog/attributes/:attributeId",
      () => new HttpResponse(null, { status: 204 }),
    ),
  );
}

export function aLocation(overrides: Partial<LocationNode> = {}): LocationNode {
  return {
    id: "0199ffff-0000-7000-8000-000000000001",
    parent_id: null,
    code: "WX-L-0001",
    name: "Lab",
    created_at: "2026-09-20T10:00:00Z",
    child_count: 0,
    lot_count: 0,
    ...overrides,
  };
}

export function respondWithLocations(locations: LocationNode[]) {
  server.use(http.get("*/api/inventory/locations", () => HttpResponse.json(locations)));
}

/** Takes a new location and answers with it and a minted code. Holds every body sent. */
export function acceptNewLocations(created: LocationNode = aLocation()): NewLocation[] {
  const sent: NewLocation[] = [];
  server.use(
    http.post("*/api/inventory/locations", async ({ request }) => {
      sent.push((await request.json()) as NewLocation);
      return HttpResponse.json(
        {
          id: created.id,
          parent_id: created.parent_id,
          code: created.code,
          name: created.name,
          created_at: created.created_at,
        },
        { status: 201 },
      );
    }),
  );
  return sent;
}

/** Refuses a create the way the API does when a sibling already uses the name (1.3). */
export function refuseNewLocations(detail: string, status = 409) {
  server.use(
    http.post("*/api/inventory/locations", () => HttpResponse.json({ detail }, { status })),
  );
}

export function acceptLocationEdits(edited: LocationNode = aLocation()): LocationChange[] {
  const sent: LocationChange[] = [];
  server.use(
    http.patch("*/api/inventory/locations/:locationId", async ({ request }) => {
      sent.push((await request.json()) as LocationChange);
      return HttpResponse.json({
        id: edited.id,
        parent_id: edited.parent_id,
        code: edited.code,
        name: edited.name,
        created_at: edited.created_at,
      });
    }),
  );
  return sent;
}

/** Refuses an edit the way the API does when a sibling already uses the name (1.7). */
export function refuseLocationEdits(detail: string, status = 409) {
  server.use(
    http.patch("*/api/inventory/locations/:locationId", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

export function acceptLocationDeletion() {
  server.use(
    http.delete(
      "*/api/inventory/locations/:locationId",
      () => new HttpResponse(null, { status: 204 }),
    ),
  );
}

/** Refuses a delete the way the API refuses one still holding lots or children (9.2). */
export function refuseLocationDeletion(detail: string, status = 409) {
  server.use(
    http.delete("*/api/inventory/locations/:locationId", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

export function aBalance(overrides: Partial<BalanceResponse> = {}): BalanceResponse {
  return {
    lot_id: "0199eeee-0000-7000-8000-0000000000b1",
    on_hand: 100,
    reserved: 0,
    available: 100,
    ...overrides,
  };
}

/** One part's total and per-location breakdown; any other part is a fresh, empty one (7.4). */
export function respondWithPartStock(partId: string, stock: PartStock) {
  server.use(
    http.get("*/api/inventory/parts/:partId/stock", ({ params }) =>
      params.partId === partId
        ? HttpResponse.json(stock)
        : HttpResponse.json({ total: 0, breakdown: [] }),
    ),
  );
}

/**
 * The batch totals the parts list asks for: only the parts with stock come back, keyed by
 * the ids in the query, the way the API answers (requirements 7.1, 7.2). The array holds the
 * ids each request asked about, so a test can check the page batched them into one query.
 */
export function respondWithPartTotals(totals: PartTotal[]): string[][] {
  const asked: string[][] = [];
  server.use(
    http.get("*/api/inventory/parts/stock", ({ request }) => {
      const ids = new URL(request.url).searchParams.getAll("part_id");
      asked.push(ids);
      return HttpResponse.json(totals.filter((total) => ids.includes(total.part_id)));
    }),
  );
  return asked;
}

/** Takes a receive and answers with the resulting balance. Holds every body sent. */
export function acceptReceive(balance: BalanceResponse = aBalance()): ReceiveRequest[] {
  const sent: ReceiveRequest[] = [];
  server.use(
    http.post("*/api/inventory/receive", async ({ request }) => {
      sent.push((await request.json()) as ReceiveRequest);
      return HttpResponse.json(balance, { status: 201 });
    }),
  );
  return sent;
}

/** Takes an adjust and answers with the resulting balance. Holds every body sent. */
export function acceptAdjust(balance: BalanceResponse = aBalance()): AdjustRequest[] {
  const sent: AdjustRequest[] = [];
  server.use(
    http.post("*/api/inventory/adjust", async ({ request }) => {
      sent.push((await request.json()) as AdjustRequest);
      return HttpResponse.json(balance);
    }),
  );
  return sent;
}

/** Takes a move and answers with both lots' balances. Holds every body sent. */
export function acceptMove(
  response: MoveResponse = { source: aBalance({ on_hand: 60 }), destination: aBalance() },
): MoveRequest[] {
  const sent: MoveRequest[] = [];
  server.use(
    http.post("*/api/inventory/move", async ({ request }) => {
      sent.push((await request.json()) as MoveRequest);
      return HttpResponse.json(response);
    }),
  );
  return sent;
}

/** Refuses a receive the way the API does, e.g. a unit-tracked part (422) or 404. */
export function refuseReceive(detail: string, status = 422) {
  server.use(http.post("*/api/inventory/receive", () => HttpResponse.json({ detail }, { status })));
}

/** Refuses a move the way the API does when the source can't spare the quantity (409). */
export function refuseMove(detail: string, status = 409) {
  server.use(http.post("*/api/inventory/move", () => HttpResponse.json({ detail }, { status })));
}

export function aUnit(overrides: Partial<UnitResponse> = {}): UnitResponse {
  return {
    id: "0199dddd-0000-7000-8000-0000000000c1",
    part_id: aPart().id,
    lot_id: "0199eeee-0000-7000-8000-0000000000b1",
    code: "WX-U-0001",
    serial: null,
    mac: null,
    status: "in_stock",
    location: {
      id: aLocation().id,
      parent_id: aLocation().parent_id,
      code: aLocation().code,
      name: aLocation().name,
      created_at: aLocation().created_at,
    },
    created_at: "2026-09-26T10:00:00Z",
    ...overrides,
  };
}

/** The units of one part; any other part has none, as the API answers (requirement 6.1). */
export function respondWithUnitsOfPart(partId: string, units: UnitResponse[]) {
  server.use(
    http.get("*/api/inventory/parts/:partId/units", ({ params }) =>
      HttpResponse.json(params.partId === partId ? units : []),
    ),
  );
}

/** One unit by id; any other id is a 404, as the API answers (requirement 7.2). */
export function respondWithUnit(unit: UnitResponse) {
  server.use(
    http.get("*/api/inventory/units/:unitId", ({ params }) =>
      params.unitId === unit.id ? HttpResponse.json(unit) : notFound("that unit doesn't exist"),
    ),
  );
}

/**
 * Searches UNITS the way the API does: `search` is a case-insensitive substring of code,
 * serial or MAC. The array holds every term asked about, so a test can check the box searched.
 */
export function respondWithUnitSearch(units: UnitResponse[]): string[] {
  const asked: string[] = [];
  server.use(
    http.get("*/api/inventory/units", ({ request }) => {
      const term = (new URL(request.url).searchParams.get("search") ?? "").toLowerCase();
      asked.push(term);
      const matching = units.filter((unit) =>
        [unit.code, unit.serial, unit.mac]
          .filter((field): field is string => field != null)
          .some((field) => field.toLowerCase().includes(term)),
      );
      return HttpResponse.json(matching);
    }),
  );
  return asked;
}

/** Takes a receive and answers with the created units and the balance. Holds every body. */
export function acceptReceiveUnits(units: UnitResponse[]): ReceiveUnitsRequest[] {
  const sent: ReceiveUnitsRequest[] = [];
  server.use(
    http.post("*/api/inventory/units", async ({ request }) => {
      sent.push((await request.json()) as ReceiveUnitsRequest);
      return HttpResponse.json({ units, balance: aBalance() }, { status: 201 });
    }),
  );
  return sent;
}

/** Refuses a receive the way the API does, e.g. a lot-counted part (422) or a 404. */
export function refuseReceiveUnits(detail: string, status = 422) {
  server.use(http.post("*/api/inventory/units", () => HttpResponse.json({ detail }, { status })));
}

/** Takes a relabel and answers with the updated unit. Holds every body sent. */
export function acceptRelabelUnit(updated: UnitResponse = aUnit()): RelabelUnitRequest[] {
  const sent: RelabelUnitRequest[] = [];
  server.use(
    http.patch("*/api/inventory/units/:unitId", async ({ request }) => {
      const body = (await request.json()) as RelabelUnitRequest;
      sent.push(body);
      return HttpResponse.json({ ...updated, serial: body.serial ?? null, mac: body.mac ?? null });
    }),
  );
  return sent;
}

/** Refuses a relabel the way the API does when the serial or MAC is taken (409). */
export function refuseRelabelUnit(detail: string, status = 409) {
  server.use(
    http.patch("*/api/inventory/units/:unitId", () => HttpResponse.json({ detail }, { status })),
  );
}

/** Takes a move and answers with the moved unit. Holds every body sent. */
export function acceptMoveUnit(moved: UnitResponse = aUnit()): { to_location_id: string }[] {
  const sent: { to_location_id: string }[] = [];
  server.use(
    http.post("*/api/inventory/units/:unitId/move", async ({ request }) => {
      sent.push((await request.json()) as { to_location_id: string });
      return HttpResponse.json(moved);
    }),
  );
  return sent;
}

/** Refuses a move the way the API does for the same location or a retired unit (422). */
export function refuseMoveUnit(detail: string, status = 422) {
  server.use(
    http.post("*/api/inventory/units/:unitId/move", () =>
      HttpResponse.json({ detail }, { status }),
    ),
  );
}

/** Takes a retire and answers with the retired unit. Holds every reason sent. */
export function acceptRetireUnit(retired: UnitResponse = aUnit({ status: "retired" })): string[] {
  const sent: string[] = [];
  server.use(
    http.post("*/api/inventory/units/:unitId/retire", async ({ request }) => {
      const body = (await request.json()) as { reason: string };
      sent.push(body.reason);
      return HttpResponse.json(retired);
    }),
  );
  return sent;
}

/** Takes an un-retire and answers with the in-stock unit. Counts the calls. */
export function acceptUnretireUnit(restored: UnitResponse = aUnit({ status: "in_stock" })): {
  count: number;
} {
  const calls = { count: 0 };
  server.use(
    http.post("*/api/inventory/units/:unitId/unretire", () => {
      calls.count += 1;
      return HttpResponse.json(restored);
    }),
  );
  return calls;
}

/** Deletes a unit, the way the API answers a retired one: 204 and gone. Holds the ids. */
export function acceptDeleteUnit(): string[] {
  const sent: string[] = [];
  server.use(
    http.delete("*/api/inventory/units/:unitId", ({ params }) => {
      sent.push(String(params.unitId));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return sent;
}

/** Refuses a delete the way the API refuses an in-stock unit (409). */
export function refuseDeleteUnit(detail: string, status = 409) {
  server.use(
    http.delete("*/api/inventory/units/:unitId", () => HttpResponse.json({ detail }, { status })),
  );
}

export function aQuickAddResponse(overrides: Partial<QuickAddResponse> = {}): QuickAddResponse {
  return { part_id: aPart().id, name: aPart().name, balance: null, units: [], ...overrides };
}

/** Takes a quick-add and answers 201 with `added`, as the API does. Holds every body sent. */
export function acceptQuickAdds(added: QuickAddResponse = aQuickAddResponse()): QuickAddRequest[] {
  const sent: QuickAddRequest[] = [];
  server.use(
    http.post("*/api/inventory/quick-add", async ({ request }) => {
      sent.push((await request.json()) as QuickAddRequest);
      return HttpResponse.json(added, { status: 201 });
    }),
  );
  return sent;
}

export function aCellProblem(overrides: Partial<CellProblem> = {}): CellProblem {
  return {
    row: null,
    column: "name",
    code: "missing",
    message: "a new part needs a name",
    ...overrides,
  };
}

/** Refuses a quick-add with every problem at once, as the API's 422 does (requirement 1.5). */
export function refuseQuickAdds(problems: CellProblem[]) {
  server.use(
    http.post("*/api/inventory/quick-add", () =>
      HttpResponse.json(
        { detail: { message: "the part can't be added as it is", problems } },
        { status: 422 },
      ),
    ),
  );
}

/** Refuses a quick-add whose part number `holder` already has, as the API's 409 does (1.6). */
export function refuseQuickAddsAsTaken(holder: { id: string; name: string }) {
  server.use(
    http.post("*/api/inventory/quick-add", () =>
      HttpResponse.json(
        {
          detail: {
            message: `the number is already the part ${holder.name}`,
            part_id: holder.id,
            name: holder.name,
          },
        },
        { status: 409 },
      ),
    ),
  );
}

/** Refuses a quick-add with a plain message, as a 404 for a duplicate's missing source is. */
export function refuseQuickAddsWith(detail: string, status = 404) {
  server.use(
    http.post("*/api/inventory/quick-add", () => HttpResponse.json({ detail }, { status })),
  );
}

export function anImportSummary(overrides: Partial<ImportSummary> = {}): ImportSummary {
  return {
    rows: 1,
    new_parts: 1,
    existing_parts: 0,
    receipts: 1,
    pieces: 200,
    units: 0,
    rows_with_problems: 0,
    ...overrides,
  };
}

/** Row 2 of a sheet: a new resistor and 200 of it into Drawer 3, with no problem. */
export function anImportRow(overrides: Partial<ImportRow> = {}): ImportRow {
  const drawer = aLocation({
    id: "0199ffff-0000-7000-8000-000000000003",
    name: "Drawer 3",
    code: "WX-L-0003",
  });
  return {
    row: 2,
    part: {
      kind: "new",
      part_id: null,
      name: "10k 0805",
      category: "Passives / Resistors",
      same_as_row: null,
    },
    stock: {
      kind: "lot",
      location: {
        id: drawer.id,
        parent_id: drawer.parent_id,
        code: drawer.code,
        name: drawer.name,
        created_at: drawer.created_at,
      },
      quantity: 200,
      units: [],
    },
    problems: [],
    ...overrides,
  };
}

export function anImportPreview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    digest: "9f2c".padEnd(64, "0"),
    summary: anImportSummary(),
    problems: [],
    rows: [anImportRow()],
    ...overrides,
  };
}

/** Answers every preview with `plan`, as the API does, problems or not (7.5). Holds each sheet. */
export function respondWithImportPreviews(plan: ImportPreview = anImportPreview()): string[] {
  const sent: string[] = [];
  server.use(
    http.post("*/api/inventory/imports/preview", async ({ request }) => {
      sent.push(((await request.json()) as ImportSheetRequest).csv);
      return HttpResponse.json(plan);
    }),
  );
  return sent;
}

/** Refuses a sheet that can't be read, as the API's 422 does, with its code (4.6). */
export function refuseImportPreviewsAsUnreadable(
  code: string,
  message: string,
  column: string | null = null,
) {
  server.use(
    http.post("*/api/inventory/imports/preview", () =>
      HttpResponse.json({ detail: { message, code, column } }, { status: 422 }),
    ),
  );
}

export function anImportResult(overrides: Partial<ImportResult> = {}): ImportResult {
  return {
    summary: anImportSummary(),
    parts: [{ row: 2, part_id: aPart().id, name: "10k 0805" }],
    units: [],
    ...overrides,
  };
}

/** Takes an import and answers 201 with `result`, as the API does. Holds every body sent. */
export function acceptImports(result: ImportResult = anImportResult()): ImportRequest[] {
  const sent: ImportRequest[] = [];
  server.use(
    http.post("*/api/inventory/imports", async ({ request }) => {
      sent.push((await request.json()) as ImportRequest);
      return HttpResponse.json(result, { status: 201 });
    }),
  );
  return sent;
}

/** Refuses an import whose outcome changed since its preview, as the API's 409 does (8.3). */
export function refuseImportsAsChanged() {
  server.use(
    http.post("*/api/inventory/imports", () =>
      HttpResponse.json(
        { detail: "the sheet's outcome changed since its preview; preview it again" },
        { status: 409 },
      ),
    ),
  );
}

/** Refuses an import whose plan has problems now, as the API's 422 does (8.2). */
export function refuseImports(problems: CellProblem[]) {
  server.use(
    http.post("*/api/inventory/imports", () =>
      HttpResponse.json(
        { detail: { message: "the sheet can't be imported as it is", problems } },
        { status: 422 },
      ),
    ),
  );
}

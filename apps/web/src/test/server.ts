import type {
  AdjustRequest,
  AttachmentResponse,
  AttributeChange,
  BalanceResponse,
  Bom,
  BomLine,
  BomLineChange,
  BomPart,
  BomPartFacts,
  BomRefusal,
  CategoryChange,
  CategoryNode,
  CellProblem,
  ChangeAttachmentRequest,
  FacetsResponse,
  FilterRequest,
  FirmwareSummary,
  HeldPart,
  ImportPreview,
  ImportRequest,
  ImportResult,
  ImportRow,
  ImportSheetRequest,
  ImportSummary,
  Lifecycle,
  LifecycleRefusal,
  LocationChange,
  LocationNode,
  MoveRequest,
  MoveResponse,
  Net,
  NetChange,
  Netlist,
  NetPin,
  NetRefusal,
  NewAttribute,
  NewCategory,
  NewLocation,
  NewPart,
  NewProject,
  NewRevision,
  PartDetails,
  PartHolding,
  PartRevision,
  PartSearchRequest,
  PartStock,
  PartSummary,
  PartTotal,
  Pin,
  PinoutReplacement,
  PinUsage,
  PinUse,
  ProjectChange,
  ProjectDetails,
  ProjectSummary,
  ProjectTag,
  QuickAddRequest,
  QuickAddResponse,
  ReceiveRequest,
  ReceiveUnitsRequest,
  RelabelUnitRequest,
  RevisionChange,
  RevisionDetails,
  RevisionRef,
  RevisionStatus,
  SchemaAttribute,
  SearchResult,
  SessionInfo,
  Transition,
  UnitResponse,
} from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import type { PartUse } from "../features/catalog/catalog";
import { readDesignators } from "../features/projects/bom/designators";

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
    not_stocked: null,
    not_stocked_resolved: false,
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
    tracked_individually: false,
    not_stocked: false,
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

/**
 * A part deletion refused because bills of materials name the part, answered as the API
 * does: the first few BOMs and how many more (09's requirement 8.1).
 */
export function refusePartDeletion(uses: PartUse[], more = 0) {
  const total = uses.length + more;
  server.use(
    http.delete("*/api/catalog/parts/:partId", () =>
      HttpResponse.json(
        {
          detail: {
            message: `the part is on ${total} bills of materials; take it off them first`,
            uses,
            more,
          },
        },
        { status: 409 },
      ),
    ),
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

/**
 * One row of a part's per-location breakdown: on hand, reserved and available (10.3).
 * `reserved` defaults to zero, and `available` follows on hand less reserved unless given.
 */
export function aLotBalance(
  location: PartStock["breakdown"][number]["location"],
  on_hand: number,
  overrides: Partial<Omit<PartStock["breakdown"][number], "location">> = {},
): PartStock["breakdown"][number] {
  const reserved = overrides.reserved ?? 0;
  return { location, on_hand, reserved, available: on_hand - reserved, ...overrides };
}

/**
 * A part's stock in the new v0.5.0 shape: totals and a breakdown carrying on hand, reserved
 * and available (requirement 10.3). The totals default to the breakdown summed, so a caller
 * gives only the rows; `available` is on hand less reserved.
 */
export function aPartStock(
  breakdown: PartStock["breakdown"] = [],
  overrides: Partial<Omit<PartStock, "breakdown">> = {},
): PartStock {
  const total = overrides.total ?? breakdown.reduce((sum, row) => sum + row.on_hand, 0);
  const reserved = overrides.reserved ?? breakdown.reduce((sum, row) => sum + row.reserved, 0);
  return { total, reserved, available: total - reserved, breakdown, ...overrides };
}

/** One part's total and per-location breakdown; any other part is a fresh, empty one (7.4). */
export function respondWithPartStock(partId: string, stock: PartStock) {
  server.use(
    http.get("*/api/inventory/parts/:partId/stock", ({ params }) =>
      params.partId === partId
        ? HttpResponse.json(stock)
        : HttpResponse.json({ total: 0, reserved: 0, available: 0, breakdown: [] }),
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
    revision_id: null,
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

export function aRevision(overrides: Partial<RevisionDetails> = {}): RevisionDetails {
  return {
    id: "0199eeee-0000-7000-8000-00000000000a",
    project_id: "0199eeee-0000-7000-8000-000000000001",
    label: "A",
    summary: null,
    notes: null,
    status: "draft",
    forked_from: null,
    created_at: "2026-09-27T10:00:00Z",
    updated_at: "2026-09-27T10:00:00Z",
    ...overrides,
  };
}

/** A project with revision A, as the API answers a new one; its latest is its last revision. */
export function aProject(overrides: Partial<ProjectDetails> = {}): ProjectDetails {
  const id = overrides.id ?? "0199eeee-0000-7000-8000-000000000001";
  const revisions = overrides.revisions ?? [aRevision({ project_id: id })];
  return {
    id,
    name: "Weather station",
    description: null,
    tags: [],
    created_at: "2026-09-27T10:00:00Z",
    updated_at: "2026-09-27T10:00:00Z",
    revisions,
    latest_revision_id: revisions.at(-1)?.id ?? "",
    next_label: "B",
    ...overrides,
  };
}

export function aProjectSummary(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: "0199eeee-0000-7000-8000-000000000001",
    name: "Weather station",
    tags: [],
    revision_count: 1,
    latest_revision: {
      id: "0199eeee-0000-7000-8000-00000000000a",
      label: "A",
      summary: null,
      status: "draft",
    },
    last_activity: "2026-09-27T10:00:00Z",
    ...overrides,
  };
}

/**
 * Lists PROJECTS the way the API narrows them: `q` a case-insensitive substring of the name,
 * every `tag` carried. The array holds each request's search, so a test can check what was asked.
 */
export function respondWithProjects(projects: ProjectSummary[]): URLSearchParams[] {
  const asked: URLSearchParams[] = [];
  server.use(
    http.get("*/api/projects", ({ request }) => {
      const params = new URL(request.url).searchParams;
      asked.push(params);
      const q = (params.get("q") ?? "").toLowerCase();
      const tags = params.getAll("tag");
      return HttpResponse.json(
        projects.filter(
          (project) =>
            project.name.toLowerCase().includes(q) &&
            tags.every((tag) => project.tags.includes(tag)),
        ),
      );
    }),
  );
  return asked;
}

/** One project by id; any other id is a 404, as the API answers (requirement 1.9). */
/**
 * No photos and no files for any subject: the project page asks for both. A test that wants
 * some calls {@link respondWithAttachments} after the project helper, whose handler then wins.
 */
export function respondWithNoAttachments() {
  server.use(http.get("*/api/files/attachments", () => HttpResponse.json([])));
}

export function respondWithProject(project: ProjectDetails) {
  respondWithNoAttachments();
  respondWithEmptyBoms(() => project);
  respondWithEmptyNetlists(() => project);
  respondWithNoRevisionFirmware(() => project);
  respondWithDefaultLifecycles(() => project);
  server.use(
    http.get("*/api/projects/:projectId", ({ params }) => {
      // The API declares /projects/tags first; answering nothing here lets its handler take it.
      if (params.projectId === "tags") return undefined;
      return params.projectId === project.id
        ? HttpResponse.json(project)
        : notFound("that project doesn't exist");
    }),
  );
}

export function respondWithProjectTags(tags: ProjectTag[]) {
  server.use(http.get("*/api/projects/tags", () => HttpResponse.json(tags)));
}

/**
 * Creates projects as the API does: tags stored once and sorted, revision A with it, and the
 * new project answered on its own address too. A name in `taken` is a 409. Holds every body.
 */
export function acceptProjectCreates(taken: string[] = []): NewProject[] {
  const sent: NewProject[] = [];
  server.use(
    http.post("*/api/projects", async ({ request }) => {
      const body = (await request.json()) as NewProject;
      sent.push(body);
      if (taken.some((name) => name.toLowerCase() === body.name.toLowerCase())) {
        return HttpResponse.json(
          { detail: `there is already a project named ${body.name}` },
          { status: 409 },
        );
      }
      const created = aProject({
        id: "0199eeee-0000-7000-8000-0000000000f1",
        name: body.name,
        description: body.description ?? null,
        tags: [...new Set(body.tags ?? [])].sort(),
        revisions: [aRevision({ project_id: "0199eeee-0000-7000-8000-0000000000f1" })],
      });
      respondWithProject(created);
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  return sent;
}

/** What {@link acceptProjectWrites} was sent, in order, and the project as it stands now. */
export type ProjectWrites = {
  project: () => ProjectDetails | null;
  edits: ProjectChange[];
  additions: NewRevision[];
  forks: { source: string; body: NewRevision }[];
  revisionEdits: { revisionId: string; body: RevisionChange }[];
  deletions: string[];
};

type ProjectWriteOptions = {
  /** Answered as the 409 of deleting a project holding a revision that isn't a draft. */
  refuseProjectDelete?: string;
};

/**
 * One project that takes every write the API offers and answers its page from what it holds
 * now: edits replace the details, a new revision or a fork is a draft labelled as asked or as
 * `next_label`, a label a sibling holds (folded) is a 409, and the only revision can't go.
 */
export function acceptProjectWrites(
  initial: ProjectDetails,
  { refuseProjectDelete }: ProjectWriteOptions = {},
): ProjectWrites {
  respondWithNoAttachments();
  let project: ProjectDetails | null = initial;
  respondWithEmptyBoms(() => project);
  respondWithEmptyNetlists(() => project);
  respondWithNoRevisionFirmware(() => project);
  respondWithDefaultLifecycles(() => project);
  let counter = 0;
  const writes: ProjectWrites = {
    project: () => project,
    edits: [],
    additions: [],
    forks: [],
    revisionEdits: [],
    deletions: [],
  };

  function labelTaken(label: string, except?: string) {
    return (project?.revisions ?? []).some(
      (revision) => revision.id !== except && revision.label.toLowerCase() === label.toLowerCase(),
    );
  }

  function settle(current: ProjectDetails, revisions: RevisionDetails[]): ProjectDetails {
    const latest = revisions.at(-1);
    return {
      ...current,
      revisions,
      latest_revision_id: latest?.id ?? "",
      next_label: nextLabel(latest?.label ?? "", revisions),
    };
  }

  function draft(body: NewRevision, forkedFrom: string | null) {
    if (!project) return notFound("that project doesn't exist");
    const label = body.label ?? project.next_label ?? "B";
    if (labelTaken(label)) {
      return HttpResponse.json(
        { detail: `${project.name} already has a revision ${label}` },
        { status: 409 },
      );
    }
    counter += 1;
    const revision = aRevision({
      id: `0199eeee-0000-7000-8000-0000000001${String(counter).padStart(2, "0")}`,
      project_id: project.id,
      label,
      summary: body.summary ?? null,
      notes: body.notes ?? null,
      forked_from: forkedFrom,
      created_at: `2026-09-28T10:${String(counter).padStart(2, "0")}:00Z`,
    });
    project = settle(project, [...project.revisions, revision]);
    return HttpResponse.json(revision, { status: 201 });
  }

  server.use(
    http.get("*/api/projects/:projectId", ({ params }) => {
      if (params.projectId === "tags") return undefined;
      return project && params.projectId === project.id
        ? HttpResponse.json(project)
        : notFound("that project doesn't exist");
    }),
    http.patch("*/api/projects/:projectId", async ({ request, params }) => {
      if (!project || params.projectId !== project.id)
        return notFound("that project doesn't exist");
      const body = (await request.json()) as ProjectChange;
      writes.edits.push(body);
      project = {
        ...project,
        name: body.name,
        description: body.description ?? null,
        tags: [...new Set(body.tags ?? [])].sort(),
      };
      return HttpResponse.json(project);
    }),
    http.delete("*/api/projects/:projectId", ({ params }) => {
      if (!project || params.projectId !== project.id)
        return notFound("that project doesn't exist");
      if (refuseProjectDelete) {
        return HttpResponse.json({ detail: refuseProjectDelete }, { status: 409 });
      }
      project = null;
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/projects/:projectId/revisions", async ({ request }) => {
      const body = (await request.json()) as NewRevision;
      writes.additions.push(body);
      return draft(body, null);
    }),
    http.post("*/api/projects/revisions/:revisionId/fork", async ({ request, params }) => {
      const body = (await request.json()) as NewRevision;
      const source = String(params.revisionId);
      writes.forks.push({ source, body });
      if (!project?.revisions.some((revision) => revision.id === source)) {
        return notFound("that revision doesn't exist");
      }
      return draft(body, source);
    }),
    http.patch("*/api/projects/revisions/:revisionId", async ({ request, params }) => {
      const body = (await request.json()) as RevisionChange;
      const revisionId = String(params.revisionId);
      writes.revisionEdits.push({ revisionId, body });
      const current = project;
      if (!current?.revisions.some((revision) => revision.id === revisionId)) {
        return notFound("that revision doesn't exist");
      }
      if (labelTaken(body.label, revisionId)) {
        return HttpResponse.json(
          { detail: `${current.name} already has a revision ${body.label}` },
          { status: 409 },
        );
      }
      const revisions = current.revisions.map((revision) =>
        revision.id === revisionId
          ? {
              ...revision,
              label: body.label,
              summary: body.summary ?? null,
              notes: body.notes ?? null,
            }
          : revision,
      );
      project = settle(current, revisions);
      return HttpResponse.json(revisions.find((revision) => revision.id === revisionId));
    }),
    http.delete("*/api/projects/revisions/:revisionId", ({ params }) => {
      const revisionId = String(params.revisionId);
      writes.deletions.push(revisionId);
      const current = project;
      if (!current?.revisions.some((revision) => revision.id === revisionId)) {
        return notFound("that revision doesn't exist");
      }
      if (current.revisions.length === 1) {
        return HttpResponse.json(
          { detail: "a project keeps at least one revision; delete the project instead" },
          { status: 409 },
        );
      }
      project = settle(
        current,
        current.revisions
          .filter((revision) => revision.id !== revisionId)
          .map((revision) =>
            revision.forked_from === revisionId ? { ...revision, forked_from: null } : revision,
          ),
      );
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return writes;
}

/** The next single letter after LABEL that no revision holds; enough for the fakes. */
function nextLabel(label: string, revisions: RevisionDetails[]): string {
  const held = new Set(revisions.map((revision) => revision.label.toUpperCase()));
  let code = /^[A-Y]$/i.test(label) ? label.toUpperCase().charCodeAt(0) + 1 : 65;
  while (held.has(String.fromCharCode(code)) && code < 90) code += 1;
  return String.fromCharCode(code);
}

export function aBomLine(overrides: Partial<BomLine> = {}): BomLine {
  return {
    id: "0199abab-0000-7000-8000-000000000001",
    revision_id: aRevision().id,
    part_id: aPart().id,
    designators: ["R1", "R2", "R3", "R4"],
    designator_text: "R1–R4",
    quantity: 4,
    notes: null,
    created_at: "2026-09-28T10:00:00Z",
    ...overrides,
  };
}

/** What the catalog says of aPart() on a BOM: stocked, counted as a lot. */
export function aBomPartFacts(overrides: Partial<BomPartFacts> = {}): BomPartFacts {
  const part = aPart();
  return {
    name: part.name,
    manufacturer: part.manufacturer,
    mpn: part.mpn,
    package: part.package,
    tracked_individually: false,
    not_stocked: false,
    ...overrides,
  };
}

/** The report's entry for aPart(): stocked, four needed and all four there. */
export function aBomPart(overrides: Partial<BomPart> = {}): BomPart {
  return {
    part_id: aPart().id,
    lines: 1,
    need: 4,
    available: 180,
    short: 0,
    status: "covered",
    part: aBomPartFacts(),
    ...overrides,
  };
}

/**
 * A draft revision's BOM holding LINES, its report built from PARTS the way the API sums it:
 * the counts come from the parts' statuses, and it is complete with none short or unknown.
 */
export function aBom(
  { lines = [aBomLine()], parts = [aBomPart()] }: { lines?: BomLine[]; parts?: BomPart[] } = {},
  overrides: Partial<Bom> = {},
): Bom {
  const count = (status: BomPart["status"]) => parts.filter((p) => p.status === status).length;
  return {
    revision_id: aRevision().id,
    status: "draft",
    editable: true,
    lines,
    report: {
      summary: {
        lines: lines.length,
        parts: parts.length,
        short_parts: count("short"),
        short_pieces: parts.reduce((sum, part) => sum + part.short, 0),
        not_stocked_parts: count("not_stocked"),
        unknown_parts: count("unknown_part"),
        complete: count("short") === 0 && count("unknown_part") === 0,
      },
      parts,
    },
    ...overrides,
  };
}

/**
 * One revision's BOM; any other revision is a 404, as the API answers. The array holds the
 * revision id of every read, so a test can see the BOM fetched again after a write.
 */
export function respondWithBom(bom: Bom): string[] {
  const reads: string[] = [];
  server.use(
    http.get("*/api/projects/revisions/:revisionId/bom", ({ params }) => {
      reads.push(String(params.revisionId));
      return params.revisionId === bom.revision_id
        ? HttpResponse.json(bom)
        : notFound("that revision doesn't exist");
    }),
  );
  return reads;
}

/**
 * An empty BOM for every revision of the project as it stands, editable only for a draft:
 * the revision panel asks for one. A test about the BOM calls {@link respondWithBom} after.
 */
function respondWithEmptyBoms(project: () => ProjectDetails | null) {
  server.use(
    http.get("*/api/projects/revisions/:revisionId/bom", ({ params }) => {
      const revision = project()?.revisions.find((r) => r.id === params.revisionId);
      if (!revision) return notFound("that revision doesn't exist");
      const status: RevisionStatus = revision.status;
      return HttpResponse.json(
        aBom(
          { lines: [], parts: [] },
          { revision_id: revision.id, status, editable: status === "draft" },
        ),
      );
    }),
  );
}

export function aNetPin(overrides: Partial<NetPin> = {}): NetPin {
  return {
    ref: "U1.25",
    designator: "U1",
    pin: "25",
    resolution: "resolved",
    part_id: "0199aaaa-0000-7000-8000-00000000e532",
    part_name: "ESP32-DevKitC",
    label: "GPIO21",
    type: "io",
    voltage: "3.3",
    ...overrides,
  };
}

export function aNet(overrides: Partial<Net> = {}): Net {
  const pins = overrides.pins ?? [aNetPin()];
  return {
    id: "0199aaaa-0000-7000-8000-0000000000e1",
    name: "SDA",
    color: "blue",
    notes: null,
    pins_text: pins.map((pin) => pin.ref).join(", "),
    ...overrides,
    pins,
  };
}

/** A netlist whose summary adds up from its nets, as the API's does (spec 11, 4.5). */
export function aNetlist(overrides: Partial<Netlist> = {}): Netlist {
  const nets = overrides.nets ?? [aNet()];
  const pins = nets.flatMap((net) => net.pins);
  const findings = overrides.findings ?? [];
  return {
    editable: true,
    designators: [],
    parts: [],
    ...overrides,
    nets,
    findings,
    summary: {
      nets: nets.length,
      references: pins.length,
      unchecked: pins.filter((pin) => pin.resolution === "unchecked").length,
      unresolved: pins.filter((pin) => !["resolved", "unchecked"].includes(pin.resolution)).length,
      errors: findings.filter((finding) => finding.severity === "error").length,
      warnings: findings.filter((finding) => finding.severity === "warning").length,
    },
  };
}

/**
 * One revision's netlist; any other revision is a 404. The array holds the revision id of
 * every read, so a test can see the netlist fetched again after a write.
 */
export function respondWithNetlist(revisionId: string, netlist: Netlist): string[] {
  const reads: string[] = [];
  server.use(
    http.get("*/api/projects/revisions/:revisionId/netlist", ({ params }) => {
      reads.push(String(params.revisionId));
      return params.revisionId === revisionId
        ? HttpResponse.json(netlist)
        : notFound("that revision doesn't exist");
    }),
  );
  return reads;
}

export function aPinUse(overrides: Partial<PinUse> = {}): PinUse {
  return {
    project_id: "0199aaaa-0000-7000-8000-00000000a001",
    project_name: "Weather station",
    revision_id: "0199aaaa-0000-7000-8000-00000000b001",
    revision_label: "A",
    status: "draft",
    designator: "U1",
    net_id: "0199aaaa-0000-7000-8000-00000000c001",
    net_name: "SDA",
    color: null,
    ...overrides,
  };
}

/** A part's pin usage: no pinout and no uses unless given (12-wiring-validation). */
export function aPinUsage(overrides: Partial<PinUsage> = {}): PinUsage {
  const pins = overrides.pins ?? [];
  return {
    part_id: "0199aaaa-0000-7000-8000-00000000d001",
    part_name: "ESP32-DevKitC",
    others: [],
    ...overrides,
    pins,
    has_pinout: pins.length > 0,
  };
}

/** One part's pin usage; any other part answers 404, as a part the bench doesn't hold. */
export function respondWithPinUsage(partId: string, usage: PinUsage): string[] {
  const reads: string[] = [];
  server.use(
    http.get("*/api/projects/parts/:partId/pin-usage", ({ params }) => {
      reads.push(String(params.partId));
      return params.partId === partId
        ? HttpResponse.json(usage)
        : notFound("that part doesn't exist");
    }),
  );
  return reads;
}

/**
 * An empty netlist for every revision of the project as it stands, editable only for a draft:
 * the revision panel asks for one. A test about wiring calls {@link respondWithNetlist} after.
 */
function respondWithEmptyNetlists(project: () => ProjectDetails | null) {
  server.use(
    http.get("*/api/projects/revisions/:revisionId/netlist", ({ params }) => {
      const revision = project()?.revisions.find((r) => r.id === params.revisionId);
      if (!revision) return notFound("that revision doesn't exist");
      return HttpResponse.json(aNetlist({ nets: [], editable: revision.status === "draft" }));
    }),
  );
}

/**
 * No firmware for every revision of the project as it stands, and a 404 for any other, as the
 * API answers (spec 13, 3.4 and 3.7), so a revision panel asking which firmware a revision runs
 * is answered. A test about a revision's firmware answers its own after, whose handler then wins.
 */
function respondWithNoRevisionFirmware(project: () => ProjectDetails | null) {
  server.use(
    http.get("*/api/firmware/revisions/:revisionId", ({ params }) => {
      const revision = project()?.revisions.find((r) => r.id === params.revisionId);
      if (!revision) return notFound("that revision doesn't exist");
      const none: FirmwareSummary[] = [];
      return HttpResponse.json(none);
    }),
  );
}

/** What {@link acceptNetWrites} was sent, in order, and the netlist as it stands now. */
export type NetWrites = {
  netlist: () => Netlist;
  additions: NetChange[];
  edits: { netId: string; body: NetChange }[];
  removals: string[];
};

/**
 * One revision's netlist, which takes net writes the way the API does in its simplest form:
 * each typed pin kept as written, upper-cased and resolved. `refuse` answers the next write
 * with that refusal instead, once, as the API would (spec 11, Error Handling).
 */
export function acceptNetWrites(
  revisionId: string,
  initial: Netlist,
  refuse: { status: number; body: Partial<NetRefusal> } | null = null,
): NetWrites {
  let nets = [...initial.nets];
  let pending = refuse;
  let counter = 0;
  const current = () => aNetlist({ ...initial, nets });
  const writes: NetWrites = { netlist: current, additions: [], edits: [], removals: [] };

  function refusal() {
    if (!pending) return null;
    const { status, body } = pending;
    pending = null;
    const detail: NetRefusal = {
      message: "refused",
      code: "unknown_pin",
      field: "pins",
      item: null,
      candidates: [],
      net_id: null,
      net: null,
      ...body,
    };
    return HttpResponse.json({ detail }, { status });
  }

  function netFrom(body: NetChange, id: string): Net {
    const pins = body.pins
      .split(/[\s,]+/)
      .filter(Boolean)
      .map((text) => {
        const ref = text.toUpperCase();
        const [designator = "", pin = ""] = ref.split(".");
        return aNetPin({ ref, designator, pin, label: null });
      });
    return aNet({
      id,
      name: body.name.trim(),
      color: body.color ?? null,
      notes: body.notes ?? null,
      pins,
    });
  }

  server.use(
    http.get("*/api/projects/revisions/:revisionId/netlist", ({ params }) =>
      params.revisionId === revisionId
        ? HttpResponse.json(current())
        : notFound("that revision doesn't exist"),
    ),
    http.post("*/api/projects/revisions/:revisionId/netlist/nets", async ({ request }) => {
      const body = (await request.json()) as NetChange;
      const refused = refusal();
      if (refused) return refused;
      writes.additions.push(body);
      counter += 1;
      const net = netFrom(
        body,
        `0199aaaa-0000-7000-8000-00000000f${String(counter).padStart(3, "0")}`,
      );
      nets = [...nets, net];
      return HttpResponse.json(net, { status: 201 });
    }),
    http.patch(
      "*/api/projects/revisions/:revisionId/netlist/nets/:netId",
      async ({ params, request }) => {
        const body = (await request.json()) as NetChange;
        const refused = refusal();
        if (refused) return refused;
        const netId = String(params.netId);
        writes.edits.push({ netId, body });
        const net = netFrom(body, netId);
        nets = nets.map((held) => (held.id === netId ? net : held));
        return HttpResponse.json(net);
      },
    ),
    http.delete("*/api/projects/revisions/:revisionId/netlist/nets/:netId", ({ params }) => {
      const netId = String(params.netId);
      writes.removals.push(netId);
      nets = nets.filter((held) => held.id !== netId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return writes;
}

/** The transitions a status allows, in the order the API lists them (spec 10, decision 11). */
const TRANSITIONS_FROM: Record<RevisionStatus, Transition[]> = {
  draft: ["reserve"],
  reserved: ["cancel", "build"],
  built: ["dismantle"],
  dismantled: [],
};

/**
 * A lifecycle for every revision of the project as it stands, its transitions following the
 * revision's status and holding nothing. The revision panel asks for one. A test about what a
 * build holds calls {@link respondWithLifecycle} after, whose handler then wins.
 */
function respondWithDefaultLifecycles(project: () => ProjectDetails | null) {
  server.use(
    http.get("*/api/projects/revisions/:revisionId/lifecycle", ({ params }) => {
      const revision = project()?.revisions.find((r) => r.id === params.revisionId);
      if (!revision) return notFound("that revision doesn't exist");
      const status: RevisionStatus = revision.status;
      return HttpResponse.json(
        aLifecycle({
          status,
          transitions: TRANSITIONS_FROM[status],
          deletable: (status === "draft" || status === "dismantled") && hasSiblings(project()),
        }),
      );
    }),
  );
}

function hasSiblings(project: ProjectDetails | null): boolean {
  return (project?.revisions.length ?? 0) > 1;
}

/**
 * Offers PARTS to a part picker the way catalog's search does: the typed text a substring of
 * name, manufacturer, part number or package, at most the limit asked. Holds every search sent.
 */
export function respondWithPartSuggestions(parts: PartSummary[]): PartSearchRequest[] {
  return respondWithSearch(parts.map((part) => aSearchResult(part)));
}

/** What {@link acceptBomWrites} was sent, in order, and the BOM as it stands now. */
export type BomWrites = {
  bom: () => Bom;
  additions: BomLineChange[];
  edits: { lineId: string; body: BomLineChange }[];
  removals: string[];
};

/**
 * One draft revision's BOM that takes every line write and answers from what it holds now,
 * refusing as the API does: a list the designator rules refuse, a designator another line
 * holds (409, naming that line), a part CATALOG doesn't hold, a quantity that disagrees with
 * the designators or is out of range, and notes over 500 characters. CATALOG is what the
 * report knows of each part, its available stock included; the report is summed again at
 * every read, so a test sees the shortages move.
 */
export function acceptBomWrites(
  initial: Bom,
  catalog: BomPart[] = initial.report.parts,
): BomWrites {
  let lines = [...initial.lines];
  let counter = 0;
  const current = () =>
    aBom(
      { lines, parts: reportOf(lines, catalog) },
      {
        revision_id: initial.revision_id,
        status: initial.status,
        editable: initial.editable,
      },
    );
  const writes: BomWrites = { bom: current, additions: [], edits: [], removals: [] };

  function refused(
    status: number,
    refusal: Omit<BomRefusal, "line_id" | "line"> & { line?: BomLine },
  ) {
    const { line, ...rest } = refusal;
    return HttpResponse.json(
      { detail: { ...rest, line_id: line?.id ?? null, line: line?.designator_text ?? null } },
      { status },
    );
  }

  /** The line the body describes, or the refusal the API would answer instead. */
  function lineFrom(body: BomLineChange, id: string, createdAt: string) {
    const reading = readDesignators(body.designators ?? "");
    if (reading.problem) {
      return refused(422, { message: "refused", ...reading.problem, field: "designators" });
    }
    for (const designator of reading.designators) {
      const name = `${designator.letters}${designator.number}`;
      const holder = lines.find((line) => line.id !== id && line.designators.includes(name));
      if (holder) {
        const message = `${name} is already on the line ${holder.designator_text}`;
        return refused(409, {
          message,
          code: "designator_taken",
          field: "designators",
          item: name,
          line: holder,
        });
      }
    }
    if (!catalog.some((part) => part.part_id === body.part_id && part.part !== null)) {
      return refused(422, { message: "refused", code: "unknown_part", field: "part", item: null });
    }
    const quantity = body.quantity ?? null;
    if (reading.count > 0 && quantity !== null && quantity !== reading.count) {
      return refused(422, {
        message: "refused",
        code: "quantity_mismatch",
        field: "quantity",
        item: null,
      });
    }
    if (reading.count === 0 && (quantity === null || quantity < 1 || quantity > 10_000)) {
      return refused(422, {
        message: "refused",
        code: "invalid_quantity",
        field: "quantity",
        item: null,
      });
    }
    const notes = (body.notes ?? "").trim().replace(/\s+/g, " ");
    if (notes.length > 500) {
      return refused(422, {
        message: "refused",
        code: "invalid_notes",
        field: "notes",
        item: null,
      });
    }
    const line: BomLine = {
      id,
      revision_id: initial.revision_id,
      part_id: body.part_id,
      designators: reading.designators.map((d) => `${d.letters}${d.number}`),
      designator_text: reading.text,
      quantity: reading.count > 0 ? reading.count : (quantity ?? 0),
      notes: notes || null,
      created_at: createdAt,
    };
    return line;
  }

  server.use(
    http.get("*/api/projects/revisions/:revisionId/bom", ({ params }) =>
      params.revisionId === initial.revision_id
        ? HttpResponse.json(current())
        : notFound("that revision doesn't exist"),
    ),
    http.post("*/api/projects/revisions/:revisionId/bom/lines", async ({ request }) => {
      const body = (await request.json()) as BomLineChange;
      writes.additions.push(body);
      counter += 1;
      const id = `0199abab-0000-7000-8000-0000000001${String(counter).padStart(2, "0")}`;
      const made = lineFrom(body, id, `2026-09-28T11:${String(counter).padStart(2, "0")}:00Z`);
      if (made instanceof Response) return made;
      lines = [...lines, made];
      return HttpResponse.json(made, { status: 201 });
    }),
    http.patch(
      "*/api/projects/revisions/:revisionId/bom/lines/:lineId",
      async ({ request, params }) => {
        const body = (await request.json()) as BomLineChange;
        const lineId = String(params.lineId);
        writes.edits.push({ lineId, body });
        const held = lines.find((line) => line.id === lineId);
        if (!held) return notFound("that line isn't on this revision's BOM");
        const made = lineFrom(body, lineId, held.created_at);
        if (made instanceof Response) return made;
        lines = lines.map((line) => (line.id === lineId ? made : line));
        return HttpResponse.json(made);
      },
    ),
    http.delete("*/api/projects/revisions/:revisionId/bom/lines/:lineId", ({ params }) => {
      const lineId = String(params.lineId);
      writes.removals.push(lineId);
      lines = lines.filter((line) => line.id !== lineId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return writes;
}

/** Refuses every line write with DETAIL, as a locked BOM's 409 or FastAPI's own 422 list do. */
export function refuseBomWrites(detail: unknown, status: number) {
  const answer = () => HttpResponse.json({ detail }, { status });
  server.use(
    http.post("*/api/projects/revisions/:revisionId/bom/lines", answer),
    http.patch("*/api/projects/revisions/:revisionId/bom/lines/:lineId", answer),
    http.delete("*/api/projects/revisions/:revisionId/bom/lines/:lineId", answer),
  );
}

/** The report's parts for LINES, summed the way the API sums them, first appearance first. */
function reportOf(lines: BomLine[], catalog: BomPart[]): BomPart[] {
  const needs = new Map<string, { lines: number; need: number }>();
  for (const line of lines) {
    const held = needs.get(line.part_id) ?? { lines: 0, need: 0 };
    needs.set(line.part_id, { lines: held.lines + 1, need: held.need + line.quantity });
  }
  return [...needs].map(([partId, { lines: count, need }]) => {
    const known = catalog.find((part) => part.part_id === partId && part.part !== null);
    if (!known?.part) {
      return aBomPart({
        part_id: partId,
        lines: count,
        need,
        available: null,
        short: 0,
        status: "unknown_part",
        part: null,
      });
    }
    if (known.part.not_stocked) {
      return { ...known, lines: count, need, available: null, short: 0, status: "not_stocked" };
    }
    const available = known.available ?? 0;
    const short = Math.max(0, need - available);
    return {
      ...known,
      lines: count,
      need,
      available,
      short,
      status: short > 0 ? "short" : "covered",
    };
  });
}

/* ---------------------------------------------------------------------------------------- */
/* Build lifecycle (spec 10): the reserve, cancel, build and dismantle routes, the lifecycle */
/* read, revision refs and a part's holdings.                                                */
/* ---------------------------------------------------------------------------------------- */

/** A revision's build as the lifecycle read answers it: a draft holding nothing by default. */
export function aLifecycle(overrides: Partial<Lifecycle> = {}): Lifecycle {
  return {
    status: "draft",
    transitions: ["reserve"],
    deletable: true,
    parts: [],
    ...overrides,
  };
}

/** One part a reserved or built revision holds, with what it reserves, consumes and its units. */
export function aHeldPart(overrides: Partial<HeldPart> = {}): HeldPart {
  return {
    part_id: aPart().id,
    part: aBomPartFacts(),
    reserved: [],
    consumed: 0,
    units: [],
    ...overrides,
  };
}

/** A revision found by its id alone: enough to name it and link to its project. */
export function aRevisionRef(overrides: Partial<RevisionRef> = {}): RevisionRef {
  const revision = aRevision();
  return {
    id: revision.id,
    label: revision.label,
    summary: revision.summary,
    status: revision.status,
    project_id: revision.project_id,
    project_name: "Weather station",
    ...overrides,
  };
}

/**
 * One revision's lifecycle; any other revision is a 404, as the API answers. The array holds
 * the id of every read, so a test can see it fetched again after a transition.
 */
export function respondWithLifecycle(revisionId: string, lifecycle: Lifecycle): string[] {
  const reads: string[] = [];
  server.use(
    http.get("*/api/projects/revisions/:revisionId/lifecycle", ({ params }) => {
      reads.push(String(params.revisionId));
      return params.revisionId === revisionId
        ? HttpResponse.json(lifecycle)
        : notFound("that revision doesn't exist");
    }),
  );
  return reads;
}

/** One revision by its id alone; any other id is a 404 (requirement 10.2). */
export function respondWithRevisionRef(ref: RevisionRef) {
  server.use(
    http.get("*/api/projects/revisions/:revisionId", ({ params }) =>
      params.revisionId === ref.id
        ? HttpResponse.json(ref)
        : notFound("that revision doesn't exist"),
    ),
  );
}

/** One revision holding a part, with how many it reserves and how many its build consumed. */
export function aPartHolding(overrides: Partial<PartHolding> = {}): PartHolding {
  return { revision: aRevisionRef(), reserved: 0, consumed: 0, ...overrides };
}

/** A part's holdings: each revision holding some of it (requirement 10.4). Any part may hold. */
export function respondWithPartHoldings(partId: string, holdings: PartHolding[]) {
  server.use(
    http.get("*/api/projects/parts/:partId/holdings", ({ params }) =>
      HttpResponse.json(params.partId === partId ? holdings : []),
    ),
  );
}

/**
 * Takes the four transitions and answers each with `revision`, as the API does. The arrays
 * hold what each was sent, so a test can check the units a reserve named or the location a
 * dismantle chose.
 */
export function acceptTransitions(revision: RevisionDetails = aRevision()): {
  reserves: { units: string[] }[];
  cancels: string[];
  builds: string[];
  dismantles: { location_id: string }[];
} {
  const calls = {
    reserves: [] as { units: string[] }[],
    cancels: [] as string[],
    builds: [] as string[],
    dismantles: [] as { location_id: string }[],
  };
  server.use(
    http.post("*/api/projects/revisions/:revisionId/reserve", async ({ request }) => {
      const body = (await request.json().catch(() => ({}))) as { units?: string[] };
      calls.reserves.push({ units: body.units ?? [] });
      return HttpResponse.json({ ...revision, status: "reserved" });
    }),
    http.post("*/api/projects/revisions/:revisionId/cancel", ({ params }) => {
      calls.cancels.push(String(params.revisionId));
      return HttpResponse.json({ ...revision, status: "draft" });
    }),
    http.post("*/api/projects/revisions/:revisionId/build", ({ params }) => {
      calls.builds.push(String(params.revisionId));
      return HttpResponse.json({ ...revision, status: "built" });
    }),
    http.post("*/api/projects/revisions/:revisionId/dismantle", async ({ request }) => {
      const body = (await request.json()) as { location_id: string };
      calls.dismantles.push(body);
      return HttpResponse.json({ ...revision, status: "dismantled" });
    }),
  );
  return calls;
}

/**
 * Refuses a transition the way the API does: `detail` is the `LifecycleRefusalResponse`, with
 * the code the web translates, on the transition's own route.
 */
export function refuseTransition(
  transition: Transition,
  refusal: Partial<LifecycleRefusal> & Pick<LifecycleRefusal, "code">,
  status = 409,
) {
  const detail: LifecycleRefusal = {
    message: "refused",
    transition,
    status: null,
    unit_id: null,
    unit_code: null,
    report: null,
    ...refusal,
  };
  const route = `*/api/projects/revisions/:revisionId/${transition}`;
  server.use(http.post(route, () => HttpResponse.json({ detail }, { status })));
}

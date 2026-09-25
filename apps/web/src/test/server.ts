import type {
  AttachmentResponse,
  AttributeChange,
  CategoryChange,
  CategoryNode,
  ChangeAttachmentRequest,
  NewAttribute,
  NewCategory,
  NewPart,
  PartDetails,
  PartRevision,
  PartSummary,
  Pin,
  PinoutReplacement,
  SchemaAttribute,
  SessionInfo,
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
  server.use(
    http.get("*/api/catalog/categories/:categoryId/schema", ({ params }) => {
      if (params.categoryId !== category.id) return notFound("that category doesn't exist");
      return HttpResponse.json({
        category: {
          id: category.id,
          parent_id: category.parent_id,
          name: category.name,
          created_at: category.created_at,
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
      sent.push((await request.json()) as CategoryChange);
      return HttpResponse.json({
        id: edited.id,
        parent_id: edited.parent_id,
        name: edited.name,
        created_at: edited.created_at,
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

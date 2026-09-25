import createClient from "openapi-fetch";
import type { components, paths } from "./generated/schema";

export type { Middleware } from "openapi-fetch";
export type { components, paths };
export type Schemas = components["schemas"];
export type VersionInfo = Schemas["VersionResponse"];
export type UserInfo = Schemas["UserResponse"];
export type SessionInfo = Schemas["SessionResponse"];
export type CategoryNode = Schemas["CategoryNodeResponse"];
export type PartSummary = Schemas["PartSummaryResponse"];
export type PartPage = Schemas["PartPageResponse"];
export type PartDetails = Schemas["PartResponse"];
export type CategorySchema = Schemas["CategorySchemaResponse"];
export type SchemaAttribute = Schemas["SchemaAttributeResponse"];
export type AttributeKind = Schemas["AttributeKindName"];
export type AttributeValue = Schemas["AttributeValueResponse"];
export type RawAttributeValue = Schemas["RawAttributeValue"];
export type NewPart = Schemas["DefinePartRequest"];
export type PartRevision = Schemas["UpdatePartRequest"];
export type AttributeProblem = Schemas["AttributeProblemResponse"];
export type AttributeDetails = Schemas["AttributeResponse"];
export type Pinout = Schemas["PinoutResponse"];
export type Pin = Schemas["PinResponse"];
export type PinType = Schemas["PinTypeName"];
export type PinEdit = Schemas["PinRequest"];
export type PinoutReplacement = Schemas["ReplacePinoutRequest"];
export type NewCategory = Schemas["CreateCategoryRequest"];
export type CategoryChange = Schemas["UpdateCategoryRequest"];
export type NewAttribute = Schemas["DefineAttributeRequest"];
export type AttributeChange = Schemas["UpdateAttributeRequest"];

export function createApiClient(baseUrl: string) {
  // Look fetch up on every request instead of capturing it now, so anything that
  // wraps it later (test mocks, tracing) is honoured.
  return createClient<paths>({ baseUrl, fetch: (request) => globalThis.fetch(request) });
}

export type ApiClient = ReturnType<typeof createApiClient>;

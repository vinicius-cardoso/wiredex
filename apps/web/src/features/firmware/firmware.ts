import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import type {
  FirmwareChange,
  FirmwareDetails,
  FirmwareField,
  FirmwareRefusalCode,
  FirmwareSummary,
  FirmwareVersion,
  NewFirmware,
  NewSourceFiles,
  NewVersion,
  SourceFile,
  SourceFileChange,
  VersionChange,
  VersionSummary,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { detailOf } from "../projects/projects";

/**
 * Every firmware cache hangs off one root, apart from the projects root: a firmware's page, the
 * list it is in, its versions and the revisions it runs on all move together when a firmware,
 * a version, a file or a link changes, and the root is small, so each write drops `all`
 * (requirement 11.12). No projects write drops it: a fork's new revision reads a key nothing
 * has cached yet, and a firmware page whose *Runs on* a fork, a rename or a delete changed is
 * fetched again when it is next opened, as every query here is stale once it lands.
 */
export const firmwareKeys = {
  all: ["firmware"] as const,
  list: (q: string) => ["firmware", "list", q] as const,
  one: (firmwareId: string) => ["firmware", "one", firmwareId] as const,
  version: (versionId: string) => ["firmware", "version", versionId] as const,
  ofRevision: (revisionId: string) => ["firmware", "revision", revisionId] as const,
};

/** The list's search as the address holds it, left out when empty (requirement 11.2). */
export type FirmwareSearch = { q?: string };

/**
 * The address, parsed. Anything that doesn't fit is dropped rather than thrown, so a
 * hand-edited link still opens the list; a typed `?q=8266` arrives as a number.
 */
export function validateFirmwareSearch(raw: Record<string, unknown>): FirmwareSearch {
  const given = typeof raw.q === "number" ? String(raw.q) : raw.q;
  const q = typeof given === "string" ? given.trim() : "";
  return q ? { q } : {};
}

export function firmwareListQuery(q: string) {
  return queryOptions({
    queryKey: firmwareKeys.list(q),
    queryFn: async (): Promise<FirmwareSummary[]> => {
      // null when there is no text: the client drops it from the query string.
      const { data } = await api.GET("/api/firmware", {
        params: { query: { search: q.trim() || null } },
      });
      if (!data) throw new Error("Could not load the firmware");
      return data;
    },
    // A new search keeps the previous rows on screen until its own land, so the list
    // doesn't blink empty while typing.
    placeholderData: keepPreviousData,
  });
}

/** The workspace's firmware whose name or target holds `q`, last changed first (requirement 2). */
export function useFirmwareList(q: string) {
  return useQuery(firmwareListQuery(q));
}

export function firmwareQuery(firmwareId: string) {
  return queryOptions({
    queryKey: firmwareKeys.one(firmwareId),
    queryFn: async (): Promise<FirmwareDetails> => {
      const { data } = await api.GET("/api/firmware/{firmware_id}", {
        params: { path: { firmware_id: firmwareId } },
      });
      if (!data) throw new Error("Could not load the firmware");
      return data;
    },
  });
}

/** A firmware's page: its details, the revisions it runs on and its versions (requirement 1.8). */
export function useFirmware(firmwareId: string) {
  return useQuery(firmwareQuery(firmwareId));
}

export function revisionFirmwareQuery(revisionId: string) {
  return queryOptions({
    queryKey: firmwareKeys.ofRevision(revisionId),
    queryFn: async (): Promise<FirmwareSummary[]> => {
      const { data } = await api.GET("/api/firmware/revisions/{revision_id}", {
        params: { path: { revision_id: revisionId } },
      });
      if (!data) throw new Error("Could not load the revision's firmware");
      return data;
    },
  });
}

/** The firmware a revision runs, by name, each with its latest release (requirement 3.4). */
export function useRevisionFirmware(revisionId: string) {
  return useQuery(revisionFirmwareQuery(revisionId));
}

/**
 * The version the page opens: the one the address names, or else the highest, which the API
 * lists first (requirement 11.5). Absent for a firmware with no version, or a version that
 * isn't this firmware's.
 */
export function openVersion(
  firmware: FirmwareDetails,
  versionId: string | undefined,
): VersionSummary | undefined {
  if (versionId === undefined) return firmware.versions[0];
  return firmware.versions.find((version) => version.id === versionId);
}

export function versionQuery(versionId: string) {
  return queryOptions({
    queryKey: firmwareKeys.version(versionId),
    queryFn: async (): Promise<FirmwareVersion> => {
      const { data } = await api.GET("/api/firmware/versions/{version_id}", {
        params: { path: { version_id: versionId } },
      });
      if (!data) throw new Error("Could not load the version");
      return data;
    },
  });
}

/** A version with its changelog, its base and its files' text (requirement 5.8). */
export function useVersion(versionId: string) {
  return useQuery(versionQuery(versionId));
}

/** The fields a firmware refusal can be about, as FastAPI's own 422 names them in `loc`. */
const FIELDS: readonly FirmwareField[] = [
  "name",
  "target",
  "description",
  "version",
  "changelog",
  "path",
  "content",
  "files",
];

/**
 * A refused firmware write, with the structure the API gave it (design, Error Handling): the
 * code the screen translates, the field it shows it on and the item as typed. A body the
 * request schema refuses answers FastAPI's own list instead, whose first entry still names its
 * field. Anything else, a 404 included, keeps its sentence.
 */
export class FirmwareRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly code: FirmwareRefusalCode | null = null,
    readonly field: FirmwareField | null = null,
    readonly item: string | null = null,
  ) {
    super(detail || `the firmware API refused this with ${status}`);
  }

  static from(status: number, error: unknown): FirmwareRefusal {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    if (isRecord(detail) && typeof detail.code === "string") {
      return new FirmwareRefusal(
        status,
        typeof detail.message === "string" ? detail.message : "",
        detail.code as FirmwareRefusalCode,
        typeof detail.field === "string" ? (detail.field as FirmwareField) : null,
        typeof detail.item === "string" ? detail.item : null,
      );
    }
    if (Array.isArray(detail) && isRecord(detail[0]) && Array.isArray(detail[0].loc)) {
      const wire = detail[0].loc.at(-1);
      const field = FIELDS.find((known) => known === wire) ?? null;
      return new FirmwareRefusal(status, detailOf(error), null, field);
    }
    return new FirmwareRefusal(status, detailOf(error));
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function useCreateFirmware() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async (body: NewFirmware): Promise<FirmwareDetails> => {
      const { data, error, response } = await api.POST("/api/firmware", { body });
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    // Awaited, so the list holds the new firmware by the time anyone goes back to it.
    onSuccess: invalidate,
  });
}

export type FirmwareEdit = { firmwareId: string; body: FirmwareChange };

export function useUpdateFirmware() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ firmwareId, body }: FirmwareEdit): Promise<FirmwareDetails> => {
      const { data, error, response } = await api.PATCH("/api/firmware/{firmware_id}", {
        params: { path: { firmware_id: firmwareId } },
        body,
      });
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export function useDeleteFirmware() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async (firmwareId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/firmware/{firmware_id}", {
        params: { path: { firmware_id: firmwareId } },
      });
      // A 404 is already gone, which is what was asked.
      if (!response.ok && response.status !== 404) {
        throw FirmwareRefusal.from(response.status, error);
      }
    },
    // Not awaited: the page leaves for the list at once, rather than refetching the firmware
    // it just deleted and showing its 404 first.
    onSuccess: () => void invalidate(),
  });
}

/** A firmware and a revision it runs on, or is to (requirement 3). */
export type RunsOnLink = { firmwareId: string; revisionId: string };

/**
 * Runs a firmware on a revision, whatever the revision's status (requirement 3.1): the link
 * lives in firmware, so a locked revision takes it as a draft does (decision 2).
 */
export function useLinkRevision() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ firmwareId, revisionId }: RunsOnLink): Promise<void> => {
      const { error, response } = await api.PUT(
        "/api/firmware/{firmware_id}/revisions/{revision_id}",
        { params: { path: { firmware_id: firmwareId, revision_id: revisionId } } },
      );
      if (!response.ok) throw FirmwareRefusal.from(response.status, error);
    },
    // Awaited, so the revision lists the firmware by the time the select stops offering it.
    onSuccess: invalidate,
  });
}

export function useUnlinkRevision() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ firmwareId, revisionId }: RunsOnLink): Promise<void> => {
      const { error, response } = await api.DELETE(
        "/api/firmware/{firmware_id}/revisions/{revision_id}",
        { params: { path: { firmware_id: firmwareId, revision_id: revisionId } } },
      );
      // A 404 is a firmware already gone, and its links with it.
      if (!response.ok && response.status !== 404) {
        throw FirmwareRefusal.from(response.status, error);
      }
    },
    onSuccess: invalidate,
  });
}

export type VersionStart = { firmwareId: string; body: NewVersion };

export function useStartVersion() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ firmwareId, body }: VersionStart): Promise<FirmwareVersion> => {
      const { data, error, response } = await api.POST("/api/firmware/{firmware_id}/versions", {
        params: { path: { firmware_id: firmwareId } },
        body,
      });
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    // Awaited, so the firmware's page lists the new draft by the time it is opened.
    onSuccess: invalidate,
  });
}

export type VersionEdit = { versionId: string; body: VersionChange };

export function useUpdateVersion() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ versionId, body }: VersionEdit): Promise<FirmwareVersion> => {
      const { data, error, response } = await api.PATCH("/api/firmware/versions/{version_id}", {
        params: { path: { version_id: versionId } },
        body,
      });
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export function useReleaseVersion() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async (versionId: string): Promise<FirmwareVersion> => {
      const { data, error, response } = await api.POST(
        "/api/firmware/versions/{version_id}/release",
        { params: { path: { version_id: versionId } } },
      );
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export type VersionDeletion = { firmwareId: string; versionId: string };

/**
 * Deleting a version opens the firmware's own address, which shows its highest version
 * (requirement 11.5). Both happen here rather than in the button: the panel holding the button
 * goes with its version, and a callback given to `mutate` would go with it.
 */
export function useDeleteVersion() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: async ({ versionId }: VersionDeletion): Promise<void> => {
      const { error, response } = await api.DELETE("/api/firmware/versions/{version_id}", {
        params: { path: { version_id: versionId } },
      });
      // A 404 is already gone, which is what was asked.
      if (!response.ok && response.status !== 404) {
        throw FirmwareRefusal.from(response.status, error);
      }
    },
    onSuccess: (_, { firmwareId, versionId }) => {
      // Dropped from the page at once, so it never opens the version it just deleted while
      // the refetch is on its way.
      queryClient.setQueryData<FirmwareDetails>(
        firmwareKeys.one(firmwareId),
        (page) =>
          page && {
            ...page,
            versions: page.versions.filter((version) => version.id !== versionId),
          },
      );
      void navigate({ to: "/firmware/$firmwareId", params: { firmwareId } });
      void refreshAfterWrite(queryClient, firmwareKeys.all);
    },
  });
}

export type SourceFilesAddition = { versionId: string; body: NewSourceFiles };

/** One or several files beside a draft's others, all of them or none (requirement 7.1). */
export function useAddSourceFiles() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ versionId, body }: SourceFilesAddition): Promise<SourceFile[]> => {
      const { data, error, response } = await api.POST(
        "/api/firmware/versions/{version_id}/files",
        { params: { path: { version_id: versionId } }, body },
      );
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    // Awaited, so the version lists the new files by the time the editor closes.
    onSuccess: invalidate,
  });
}

export type SourceFileEdit = { versionId: string; fileId: string; body: SourceFileChange };

/** A draft's file, its path and text replaced whole under its id (requirement 7.8). */
export function useUpdateSourceFile() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ versionId, fileId, body }: SourceFileEdit): Promise<SourceFile> => {
      const { data, error, response } = await api.PATCH(
        "/api/firmware/versions/{version_id}/files/{file_id}",
        { params: { path: { version_id: versionId, file_id: fileId } }, body },
      );
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export type SourceFileRemoval = { versionId: string; fileId: string };

export function useRemoveSourceFile() {
  const invalidate = useFirmwareInvalidation();
  return useMutation({
    mutationFn: async ({ versionId, fileId }: SourceFileRemoval): Promise<void> => {
      const { error, response } = await api.DELETE(
        "/api/firmware/versions/{version_id}/files/{file_id}",
        { params: { path: { version_id: versionId, file_id: fileId } } },
      );
      // A 404 is already gone, which is what was asked.
      if (!response.ok && response.status !== 404) {
        throw FirmwareRefusal.from(response.status, error);
      }
    },
    onSuccess: invalidate,
  });
}

function useFirmwareInvalidation() {
  const queryClient = useQueryClient();
  return () => refreshAfterWrite(queryClient, firmwareKeys.all);
}

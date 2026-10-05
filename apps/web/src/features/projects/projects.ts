import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  NewProject,
  NewRevision,
  ProjectChange,
  ProjectDetails,
  ProjectSummary,
  ProjectTag,
  RevisionChange,
  RevisionDetails,
  RevisionStatus,
} from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { type PageSearch, validatePageSearch } from "../../shared/ui/pagination";
import { trashKeys } from "../trash/keys";

/**
 * Every projects cache hangs off one root key: a project's page, the list it is in and the
 * tag counts all move together when a project or one of its revisions changes, so each write
 * drops `all` (requirement 10.10).
 */
export const projectKeys = {
  all: ["projects"] as const,
  list: (filters: ProjectFilters) => ["projects", "list", filters] as const,
  tags: ["projects", "tags"] as const,
  project: (projectId: string) => ["projects", "project", projectId] as const,
};

/** What the list is narrowed by: a text in the name and tags every project carries. */
export type ProjectFilters = { q: string; tags: string[] };

/** The list's search as the address holds it, every default left out (requirement 10.2). */
/** The build statuses, in the order a revision moves through them. */
export const REVISION_STATUSES = [
  "draft",
  "reserved",
  "built",
  "dismantled",
] as const satisfies readonly RevisionStatus[];

export type ProjectSearch = PageSearch & {
  q?: string;
  tag?: string[];
  status?: RevisionStatus;
};

/**
 * The address, parsed. Anything that doesn't fit is dropped rather than thrown, so a
 * hand-edited link still opens the list; a lone `?tag=esp32` arrives as a string, not a list.
 */
export function validateProjectSearch(raw: Record<string, unknown>): ProjectSearch {
  const search: ProjectSearch = validatePageSearch(raw);
  const q = typeof raw.q === "string" ? raw.q.trim() : "";
  if (q) search.q = q;
  const given = Array.isArray(raw.tag) ? raw.tag : [raw.tag];
  const tags = [
    ...new Set(given.filter((tag): tag is string => typeof tag === "string" && tag.trim() !== "")),
  ];
  if (tags.length > 0) search.tag = tags;
  const status = REVISION_STATUSES.find((known) => known === raw.status);
  if (status) search.status = status;
  return search;
}

export function projectsQuery(filters: ProjectFilters) {
  return queryOptions({
    queryKey: projectKeys.list(filters),
    queryFn: async (): Promise<ProjectSummary[]> => {
      // null for what isn't set: the client drops it from the query string.
      const query = {
        q: filters.q.trim() || null,
        tag: filters.tags.length > 0 ? filters.tags : null,
      };
      const { data } = await api.GET("/api/projects", { params: { query } });
      if (!data) throw new Error("Could not load the projects");
      return data;
    },
    // A new search keeps the previous rows on screen until its own land, so the list
    // doesn't blink empty while typing.
    placeholderData: keepPreviousData,
  });
}

export function useProjects(filters: ProjectFilters) {
  return useQuery(projectsQuery(filters));
}

export function projectQuery(projectId: string) {
  return queryOptions({
    queryKey: projectKeys.project(projectId),
    queryFn: async (): Promise<ProjectDetails> => {
      const { data } = await api.GET("/api/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      if (!data) throw new Error("Could not load the project");
      return data;
    },
  });
}

export function useProject(projectId: string) {
  return useQuery(projectQuery(projectId));
}

export const projectTagsQuery = queryOptions({
  queryKey: projectKeys.tags,
  queryFn: async (): Promise<ProjectTag[]> => {
    const { data } = await api.GET("/api/projects/tags");
    if (!data) throw new Error("Could not load the tags");
    return data;
  },
});

/** The workspace's tags with their counts, for the list's chips and the tag box's hints. */
export function useProjectTags() {
  return useQuery(projectTagsQuery);
}

/** A refusal from the API, with the status and the message it gave. */
export class ProjectRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `the projects API refused this with ${status}`);
  }
}

export function useCreateProject() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async (body: NewProject): Promise<ProjectDetails> => {
      const { data, error, response } = await api.POST("/api/projects", { body });
      if (data) return data;
      throw new ProjectRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type ProjectEdit = { projectId: string; body: ProjectChange };

export function useUpdateProject() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async ({ projectId, body }: ProjectEdit): Promise<ProjectDetails> => {
      const { data, error, response } = await api.PATCH("/api/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body,
      });
      if (data) return data;
      throw new ProjectRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

/** Moves a project to the trash with its revisions (16's 1.1), which lists it next. */
export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      // A 409 says which revision isn't a draft (requirement 1.8); a 404 is already gone.
      if (!response.ok && response.status !== 404) {
        throw new ProjectRefusal(response.status, detailOf(error));
      }
    },
    // Not awaited: the page leaves for the list at once, rather than refetching the project
    // it just moved to the trash and showing its 404 first.
    onSuccess: () => void refreshAfterWrite(queryClient, projectKeys.all, trashKeys.all),
  });
}

export type RevisionAddition = { projectId: string; body: NewRevision };

export function useAddRevision() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async ({ projectId, body }: RevisionAddition): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/revisions", {
        params: { path: { project_id: projectId } },
        body,
      });
      if (data) return data;
      throw new ProjectRefusal(response.status, detailOf(error));
    },
    // Awaited, so the project holds the new revision by the time the page opens it.
    onSuccess: invalidate,
  });
}

export type RevisionFork = { revisionId: string; body: NewRevision };

export function useForkRevision() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, body }: RevisionFork): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/fork",
        { params: { path: { revision_id: revisionId } }, body },
      );
      if (data) return data;
      throw new ProjectRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type RevisionEdit = { revisionId: string; body: RevisionChange };

export function useUpdateRevision() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, body }: RevisionEdit): Promise<RevisionDetails> => {
      const { data, error, response } = await api.PATCH("/api/projects/revisions/{revision_id}", {
        params: { path: { revision_id: revisionId } },
        body,
      });
      if (data) return data;
      throw new ProjectRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useDeleteRevision() {
  const invalidate = useProjectsInvalidation();
  return useMutation({
    mutationFn: async (revisionId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/projects/revisions/{revision_id}", {
        params: { path: { revision_id: revisionId } },
      });
      // A 409 for the only revision or one that isn't a draft (requirements 5.2, 5.3).
      if (!response.ok && response.status !== 404) {
        throw new ProjectRefusal(response.status, detailOf(error));
      }
    },
    // Not awaited: the page moves to the project's own address first, so the deleted
    // revision's address never shows "no such revision" on the way.
    onSuccess: () => void invalidate(),
  });
}

function useProjectsInvalidation() {
  const queryClient = useQueryClient();
  return () => refreshAfterWrite(queryClient, projectKeys.all);
}

/** What the API said, whether it answered a plain message or a list of field errors. */
export function detailOf(error: unknown): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => String((entry as { msg?: unknown }).msg ?? ""))
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

/**
 * A tag as the server stores it (requirement 2.1): NFKC, whitespace collapsed, lower-cased.
 * The steps repeat until the text settles, as the server's do, so the chip shows exactly
 * what will be stored.
 */
export function normalizeTag(text: string): string {
  let current = text;
  for (let pass = 0; pass < 4; pass += 1) {
    const step = current.normalize("NFKC").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
    if (step === current) break;
    current = step;
  }
  return current;
}

/** A revision as the owner names it: `B – perfboard`, or just `B` without a summary. */
export function revisionName(
  t: TFunction,
  revision: Pick<RevisionDetails, "label" | "summary">,
): string {
  return revision.summary
    ? t("projects.revision.name", { label: revision.label, summary: revision.summary })
    : revision.label;
}

/** The revision the page opens on: the one named, or else the latest (requirement 10.4). */
export function openRevision(
  project: ProjectDetails,
  revisionId: string | undefined,
): RevisionDetails | undefined {
  const wanted = revisionId ?? project.latest_revision_id;
  return project.revisions.find((revision) => revision.id === wanted);
}

import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  AttributeChange,
  AttributeDetails,
  CategoryChange,
  CategoryNode,
  CategorySchema,
  NewAttribute,
  NewCategory,
  NewPart,
  PartDetails,
  PartPage,
  PartRevision,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/**
 * Every catalog cache hangs off one root key, so a change that ripples through the whole
 * catalog — a category renamed, an attribute removed — is one invalidation of `all`.
 */
export const catalogKeys = {
  all: ["catalog"] as const,
  categories: ["catalog", "categories"] as const,
  parts: (filters: PartFilters) => ["catalog", "parts", filters] as const,
  part: (partId: string) => ["catalog", "part", partId] as const,
  schema: (categoryId: string) => ["catalog", "schema", categoryId] as const,
};

/** What the parts list is narrowed by. Part of the query key, so each view caches apart. */
export type PartFilters = { search: string; categoryId: string | null };

export const categoriesQuery = queryOptions({
  queryKey: catalogKeys.categories,
  queryFn: async (): Promise<CategoryNode[]> => {
    const { data } = await api.GET("/api/catalog/categories");
    if (!data) throw new Error("Could not load the categories");
    return data;
  },
});

export function useCategories() {
  return useQuery(categoriesQuery);
}

/**
 * A keyset page of parts: the cursor is the last id of the window, so parts added
 * meanwhile can't shift what the next page holds.
 */
export function partsQuery(filters: PartFilters) {
  return infiniteQueryOptions({
    queryKey: catalogKeys.parts(filters),
    queryFn: async ({ pageParam }): Promise<PartPage> => {
      // null rather than undefined for what isn't set: the client drops both from the
      // query string, and null is what `exactOptionalPropertyTypes` lets us pass.
      const query = {
        q: filters.search.trim() || null,
        category_id: filters.categoryId,
        cursor: pageParam,
      };
      const { data } = await api.GET("/api/catalog/parts", { params: { query } });
      if (!data) throw new Error("Could not load the parts");
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    // Typing in the search box changes the key on every keystroke; showing the previous
    // rows until the new ones land keeps the list from blinking empty.
    placeholderData: keepPreviousData,
  });
}

export function useParts(filters: PartFilters) {
  return useInfiniteQuery(partsQuery(filters));
}

/** The name to show for a part's category, or null while the tree is still loading. */
export function categoryName(categories: CategoryNode[] | undefined, id: string): string | null {
  return categories?.find((category) => category.id === id)?.name ?? null;
}

/** A category with the branch below it, which is how the tree is drawn. */
export type CategoryBranch = { category: CategoryNode; children: CategoryBranch[] };

/**
 * The flat list the API answers with, turned into the tree it describes. Children keep the
 * order they arrived in, and a category whose parent isn't in the list is drawn as a root
 * rather than dropped.
 */
export function categoryTree(categories: CategoryNode[]): CategoryBranch[] {
  const branches = new Map(
    categories.map((category): [string, CategoryBranch] => [
      category.id,
      { category, children: [] },
    ]),
  );
  const roots: CategoryBranch[] = [];
  for (const branch of branches.values()) {
    const parent =
      branch.category.parent_id === null ? undefined : branches.get(branch.category.parent_id);
    if (parent) parent.children.push(branch);
    else roots.push(branch);
  }
  return roots;
}

/** The fields a category's parts have, its ancestors' included. */
export function categorySchemaQuery(categoryId: string) {
  return queryOptions({
    queryKey: catalogKeys.schema(categoryId),
    queryFn: async (): Promise<CategorySchema> => {
      const { data } = await api.GET("/api/catalog/categories/{category_id}/schema", {
        params: { path: { category_id: categoryId } },
      });
      if (!data) throw new Error("Could not load the category schema");
      return data;
    },
  });
}

/** Skipped until a category is chosen: the form has no fields to show before that. */
export function useCategorySchema(categoryId: string | null) {
  return useQuery({
    ...categorySchemaQuery(categoryId ?? ""),
    enabled: categoryId !== null && categoryId !== "",
  });
}

export function partQuery(partId: string) {
  return queryOptions({
    queryKey: catalogKeys.part(partId),
    queryFn: async (): Promise<PartDetails> => {
      const { data } = await api.GET("/api/catalog/parts/{part_id}", {
        params: { path: { part_id: partId } },
      });
      if (!data) throw new Error("Could not load the part");
      return data;
    },
  });
}

export function usePart(partId: string) {
  return useQuery(partQuery(partId));
}

/**
 * A refusal from the API, with the status and the message it gave. The message names the
 * attribute it is about, which is how the form puts it on the right field (requirement 7.5).
 */
export class CatalogRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `the catalog refused this with ${status}`);
  }
}

export function useDefinePart() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async (body: NewPart): Promise<PartDetails> => {
      const { data, error, response } = await api.POST("/api/catalog/parts", { body });
      if (data) return data;
      throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type PartEdit = { partId: string; body: PartRevision };

export function useUpdatePart() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async ({ partId, body }: PartEdit): Promise<PartDetails> => {
      const { data, error, response } = await api.PATCH("/api/catalog/parts/{part_id}", {
        params: { path: { part_id: partId } },
        body,
      });
      if (data) return data;
      throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useDeletePart() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async (partId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/catalog/parts/{part_id}", {
        params: { path: { part_id: partId } },
      });
      // 404 is what was asked for: the part is gone either way.
      if (!response.ok && response.status !== 404) {
        throw new CatalogRefusal(response.status, detailOf(error));
      }
    },
    onSuccess: invalidate,
  });
}

/**
 * One invalidation for every catalog change. A part touches its own row, the list it is in
 * and the counts on the category tree, so the cheap and correct move is to drop the lot.
 */
function useCatalogInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: catalogKeys.all });
}

/** What the API said, whether it answered a plain message or a list of field errors. */
function detailOf(error: unknown): string {
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

export function useCreateCategory() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async (body: NewCategory): Promise<CategoryNode> => {
      const { data, error, response } = await api.POST("/api/catalog/categories", { body });
      // A fresh category has nothing under it yet, which is what the tree needs to draw it.
      if (data) return { ...data, child_count: 0, part_count: 0 };
      throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type CategoryEdit = { categoryId: string; body: CategoryChange };

/** A rename, a move, or both: whatever the body carries (requirements 1.5 to 1.8). */
export function useEditCategory() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async ({ categoryId, body }: CategoryEdit): Promise<void> => {
      const { data, error, response } = await api.PATCH("/api/catalog/categories/{category_id}", {
        params: { path: { category_id: categoryId } },
        body,
      });
      if (!data) throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useDeleteCategory() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async (categoryId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/catalog/categories/{category_id}", {
        params: { path: { category_id: categoryId } },
      });
      // 409 lands here with the message saying what still hangs off it (requirement 7.8).
      if (!response.ok) throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type AttributeDefinition = { categoryId: string; body: NewAttribute };

export function useDefineAttribute() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async ({ categoryId, body }: AttributeDefinition): Promise<AttributeDetails> => {
      const { data, error, response } = await api.POST(
        "/api/catalog/categories/{category_id}/attributes",
        { params: { path: { category_id: categoryId } }, body },
      );
      if (data) return data;
      throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type AttributeEdit = { attributeId: string; body: AttributeChange };

export function useEditAttribute() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async ({ attributeId, body }: AttributeEdit): Promise<AttributeDetails> => {
      const { data, error, response } = await api.PATCH("/api/catalog/attributes/{attribute_id}", {
        params: { path: { attribute_id: attributeId } },
        body,
      });
      if (data) return data;
      throw new CatalogRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

/** Removes the definition. Values already stored keep their place and get flagged on read. */
export function useRemoveAttribute() {
  const invalidate = useCatalogInvalidation();
  return useMutation({
    mutationFn: async (attributeId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/catalog/attributes/{attribute_id}", {
        params: { path: { attribute_id: attributeId } },
      });
      if (!response.ok && response.status !== 404) {
        throw new CatalogRefusal(response.status, detailOf(error));
      }
    },
    onSuccess: invalidate,
  });
}

/** What the API said it refused, in its own words, for showing next to the control. */
export function refusalMessage(error: unknown): string | null {
  return error instanceof CatalogRefusal && error.detail ? error.detail : null;
}

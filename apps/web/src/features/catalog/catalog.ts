import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import type { CategoryNode, PartPage } from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/**
 * Every catalog cache hangs off one root key, so a change that ripples through the whole
 * catalog — a category renamed, an attribute removed — is one invalidation of `all`.
 */
export const catalogKeys = {
  all: ["catalog"] as const,
  categories: ["catalog", "categories"] as const,
  parts: (filters: PartFilters) => ["catalog", "parts", filters] as const,
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

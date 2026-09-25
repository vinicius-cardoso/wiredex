import { QueryClient } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { Language } from "@wiredex/i18n";
import type { ReactElement } from "react";
import { AppProviders } from "../app/providers";
import { createI18n } from "../shared/i18n/i18n";

export function createTestQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

export function renderWithProviders(
  ui: ReactElement,
  { language = "en" as Language, queryClient = createTestQueryClient() } = {},
) {
  return render(
    <AppProviders i18n={createI18n(language)} queryClient={queryClient}>
      {ui}
    </AppProviders>,
  );
}

/**
 * A component inside a real router at `/`, next to an `/elsewhere` page, for components that
 * use the router's hooks: links, or a blocker that asks before leaving.
 */
export function renderInRouter(
  ui: ReactElement,
  options: Parameters<typeof renderWithProviders>[1] = {},
) {
  const rootRoute = createRootRoute({ component: Outlet });
  const here = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => ui });
  const elsewhere = createRoute({
    getParentRoute: () => rootRoute,
    path: "/elsewhere",
    component: () => <p>Elsewhere</p>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([here, elsewhere]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return { ...renderWithProviders(<RouterProvider router={router} />, options), router };
}

import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  type RouterHistory,
  redirect,
} from "@tanstack/react-router";
import { currentUserQuery } from "../features/auth/auth";
import { LoginPage } from "../features/auth/LoginPage";
import { safeRedirect } from "../features/auth/redirect";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { AppLayout } from "./AppLayout";
import { NotFoundPage } from "./NotFoundPage";

export type RouterContext = { queryClient: QueryClient };

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppLayout,
  notFoundComponent: NotFoundPage,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  // Always returns the key: unvalidated search params would otherwise pass through as-is.
  validateSearch: (search: Record<string, unknown>): { redirect?: string | undefined } => ({
    redirect: safeRedirect(search.redirect),
  }),
  beforeLoad: async ({ context, search }) => {
    const user = await context.queryClient.ensureQueryData(currentUserQuery);
    if (user) throw redirect({ href: search.redirect ?? "/" });
  },
  component: LoginPage,
});

/** Every page under this layout needs a logged-in user; others go to /login first. */
const authenticatedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authenticated",
  beforeLoad: async ({ context, location }) => {
    const user = await context.queryClient.ensureQueryData(currentUserQuery);
    if (!user) throw redirect({ to: "/login", search: { redirect: location.href } });
  },
});

const dashboardRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/",
  component: DashboardPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authenticatedRoute.addChildren([dashboardRoute]),
]);

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

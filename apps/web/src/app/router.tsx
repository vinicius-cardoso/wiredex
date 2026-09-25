import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  type RouterHistory,
  redirect,
} from "@tanstack/react-router";
import { SessionsPage } from "../features/account/SessionsPage";
import { currentUserQuery } from "../features/auth/auth";
import { LoginPage } from "../features/auth/LoginPage";
import { safeRedirect } from "../features/auth/redirect";
import { CategoriesPage } from "../features/catalog/CategoriesPage";
import { NewPartPage } from "../features/catalog/PartForm";
import { PartPage } from "../features/catalog/PartPage";
import { PartsPage } from "../features/catalog/PartsPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { AppLayout } from "./AppLayout";
import { ErrorPage } from "./ErrorPage";
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

const sessionsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/sessions",
  component: SessionsPage,
});

const partsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/parts",
  component: PartsPage,
});

const newPartRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/parts/new",
  component: NewPartPage,
});

/** The id comes from the route, so the page itself only ever needs the part it shows. */
function PartRoute() {
  const { partId } = partRoute.useParams();
  return <PartPage partId={partId} />;
}

const partRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/parts/$partId",
  component: PartRoute,
});

const categoriesRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/categories",
  component: CategoriesPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authenticatedRoute.addChildren([
    dashboardRoute,
    sessionsRoute,
    partsRoute,
    newPartRoute,
    partRoute,
    categoriesRoute,
  ]),
]);

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    // Inside the layout, so the header (theme, language) stays usable.
    defaultErrorComponent: ErrorPage,
    ...(history ? { history } : {}),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

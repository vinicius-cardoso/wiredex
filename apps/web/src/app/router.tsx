import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { AppLayout } from "./AppLayout";
import { NotFoundPage } from "./NotFoundPage";

const rootRoute = createRootRoute({
  component: AppLayout,
  notFoundComponent: NotFoundPage,
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
});

const routeTree = rootRoute.addChildren([dashboardRoute]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

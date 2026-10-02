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
import { validateSearch } from "../features/catalog/search/searchParams";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { ComparePage } from "../features/firmware/ComparePage";
import { FirmwareListPage } from "../features/firmware/FirmwareListPage";
import { FirmwarePage } from "../features/firmware/FirmwarePage";
import { validateFirmwareSearch } from "../features/firmware/firmware";
import { NewFirmwarePage } from "../features/firmware/NewFirmwarePage";
import { validateCompareSearch } from "../features/firmware/source/comparable";
import { ActivityPage } from "../features/history/ActivityPage";
import { ImportPage } from "../features/inventory/intake/ImportPage";
import { LocationsPage } from "../features/inventory/LocationsPage";
import { UnitPage } from "../features/inventory/UnitPage";
import { UnitSearch } from "../features/inventory/UnitSearch";
import { NewProjectPage } from "../features/projects/ProjectForm";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { validateProjectSearch } from "../features/projects/projects";
import { TrashPage } from "../features/trash/TrashPage";
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
  // The search lives in the address (requirement 6.4); the validator drops anything that
  // doesn't fit, so a hand-edited link still opens a usable page.
  validateSearch,
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

const locationsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/locations",
  // `?selected=` opens the page on that location, as the palette finds one (19's 5.4).
  validateSearch: (search: Record<string, unknown>): { selected?: string | undefined } => ({
    selected:
      typeof search.selected === "string" && search.selected !== "" ? search.selected : undefined,
  }),
  component: LocationsPage,
});

const importRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/import",
  component: ImportPage,
});

const unitsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/units",
  component: UnitSearch,
});

/** The id comes from the route, so the page itself only ever needs the unit it shows. */
function UnitRoute() {
  const { unitId } = unitRoute.useParams();
  return <UnitPage unitId={unitId} />;
}

const unitRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/units/$unitId",
  component: UnitRoute,
});

const projectsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/projects",
  // The search box and the tag toggles live in the address (requirement 10.2).
  validateSearch: validateProjectSearch,
  component: ProjectsPage,
});

const newProjectRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/projects/new",
  component: NewProjectPage,
});

/** The project's own address opens its latest revision (requirement 10.4). */
function ProjectRoute() {
  const { projectId } = projectRoute.useParams();
  return <ProjectPage projectId={projectId} />;
}

const projectRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/projects/$projectId",
  component: ProjectRoute,
});

function ProjectRevisionRoute() {
  const { projectId, revisionId } = projectRevisionRoute.useParams();
  return <ProjectPage projectId={projectId} revisionId={revisionId} />;
}

const projectRevisionRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/projects/$projectId/revisions/$revisionId",
  component: ProjectRevisionRoute,
});

const firmwareListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/firmware",
  // The search box lives in the address (requirement 11.2).
  validateSearch: validateFirmwareSearch,
  component: FirmwareListPage,
});

const newFirmwareRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/firmware/new",
  // `?revision=` starts the firmware running on that revision (requirement 11.4).
  validateSearch: (search: Record<string, unknown>): { revision?: string | undefined } => ({
    revision:
      typeof search.revision === "string" && search.revision !== "" ? search.revision : undefined,
  }),
  component: NewFirmwarePage,
});

/** The id comes from the route, so the page itself only ever needs the firmware it shows. */
function FirmwareRoute() {
  const { firmwareId } = firmwareRoute.useParams();
  return <FirmwarePage firmwareId={firmwareId} />;
}

const firmwareRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/firmware/$firmwareId",
  component: FirmwareRoute,
});

/** The firmware's page with the named version open rather than the highest (11.5). */
function FirmwareVersionRoute() {
  const { firmwareId, versionId } = firmwareVersionRoute.useParams();
  return <FirmwarePage firmwareId={firmwareId} versionId={versionId} />;
}

const firmwareVersionRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/firmware/$firmwareId/versions/$versionId",
  component: FirmwareVersionRoute,
});

function FirmwareCompareRoute() {
  const { firmwareId } = firmwareCompareRoute.useParams();
  const search = firmwareCompareRoute.useSearch();
  return <ComparePage firmwareId={firmwareId} search={search} />;
}

const firmwareCompareRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/firmware/$firmwareId/compare",
  // The two versions live in the address, so a comparison can be bookmarked and walked with
  // Back (requirement 4.7).
  validateSearch: validateCompareSearch,
  component: FirmwareCompareRoute,
});

const activityRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/activity",
  component: ActivityPage,
});

const trashRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/trash",
  component: TrashPage,
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
    locationsRoute,
    importRoute,
    unitsRoute,
    unitRoute,
    projectsRoute,
    newProjectRoute,
    projectRoute,
    projectRevisionRoute,
    firmwareListRoute,
    newFirmwareRoute,
    firmwareRoute,
    firmwareVersionRoute,
    firmwareCompareRoute,
    activityRoute,
    trashRoute,
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

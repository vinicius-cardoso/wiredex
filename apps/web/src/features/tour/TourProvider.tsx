import { useQuery } from "@tanstack/react-query";
import { useLocation } from "@tanstack/react-router";
import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { benchCountsQuery } from "../dashboard/dashboard";
import { MissionsPanel } from "./MissionsPanel";
import { Spotlight } from "./Spotlight";
import {
  MISSIONS,
  type Mission,
  missionsDone,
  PAGE_ANCHORS,
  PAGE_TOURS,
  type PageAnchor,
  readMemory,
  STOPS,
  type Stop,
  type TourMemory,
  type TourPage,
  tourPageAt,
  writeMemory,
} from "./tour";

type Tour = {
  /** Whether there is a tour to take here: not outside the signed-in app. */
  available: boolean;
  /** Whether the dashboard should still offer it. */
  offering: boolean;
  /** Starts the look-around from its first stop; the missions follow it on an owner's bench. */
  start: () => void;
  /** Answers the dashboard's offer with "not now". */
  decline: () => void;
  /** Ticks a mission that is done by an action here, such as opening the palette. */
  mark: (id: Mission["id"]) => void;
  /** Whether the page on screen has a tour of its own. */
  pageTour: boolean;
  /** Starts the tour of the page on screen, at the first of its stops that is there. */
  startPage: () => void;
};

const NO_TOUR: Tour = {
  available: false,
  offering: false,
  start: () => {},
  decline: () => {},
  mark: () => {},
  pageTour: false,
  startPage: () => {},
};

const TourContext = createContext<Tour>(NO_TOUR);

/** The tour, from anywhere; outside a `TourProvider` there is none, and asking does nothing. */
export function useTour(): Tour {
  return use(TourContext);
}

type Props = {
  children: ReactNode;
  enabled: boolean;
  /** A guest's bench comes filled, so a guest looks around and is given no missions. */
  guest: boolean;
};

/**
 * The tour every page shares: a look-around that points at each part of the app in turn, then,
 * on an owner's bench, a list of first things to do that tick themselves as the bench fills.
 * What it remembers (the offer answered, the list open, what was done here) stays on this
 * device. While the list is open the bench is counted again every few seconds, so a mission
 * ticks soon after it is done, whichever page it was done on. Each module's page also has a
 * short tour of its own, of what is on that page, which ends when the page is left.
 */
export function TourProvider({ children, enabled, guest }: Props) {
  const [memory, setMemory] = useState<TourMemory>(readMemory);
  const [stop, setStop] = useState<number | null>(null);
  // One thing pointed at by a mission's *Show me*, outside the look-around.
  const [pointed, setPointed] = useState<Stop | null>(null);
  const { t } = useTranslation();
  const pathname = useLocation({ select: (location) => location.pathname });
  const page = tourPageAt(pathname);
  // The stops of the page's tour that were on screen when it started, and the one shown.
  const [paging, setPaging] = useState<{ stops: PageAnchor[]; at: number } | null>(null);

  const remember = useCallback((change: (memory: TourMemory) => TourMemory) => {
    setMemory((before) => {
      const after = change(before);
      writeMemory(after);
      return after;
    });
  }, []);

  const listing = enabled && !guest && memory.missions;
  const counts = useQuery({ ...benchCountsQuery, enabled: listing, refetchInterval: 4000 });
  const done = useMemo(
    () => missionsDone(counts.data, memory.marked),
    [counts.data, memory.marked],
  );

  const start = useCallback(() => {
    if (!enabled) return;
    remember((before) => ({ ...before, offered: true }));
    setPointed(null);
    setStop(0);
  }, [enabled, remember]);
  const decline = useCallback(
    () => remember((before) => ({ ...before, offered: true })),
    [remember],
  );
  const mark = useCallback(
    (id: Mission["id"]) =>
      remember((before) =>
        before.marked.includes(id) ? before : { ...before, marked: [...before.marked, id] },
      ),
    [remember],
  );

  const startPage = useCallback(() => {
    if (!enabled || !page) return;
    const stops = PAGE_TOURS[page].stops.filter((anchor) =>
      document.querySelector(PAGE_ANCHORS[anchor]),
    );
    if (stops.length === 0) return;
    setStop(null);
    setPointed(null);
    setPaging({ stops, at: 0 });
  }, [enabled, page]);

  // Signing out ends whatever was on screen.
  useEffect(() => {
    if (!enabled) {
      setStop(null);
      setPointed(null);
      setPaging(null);
    }
  }, [enabled]);

  // A page's tour is of that page: another address ends it. The address is read so the
  // effect runs when it changes.
  useEffect(() => {
    setPaging(null);
    return () => void pathname;
  }, [pathname]);

  function leave() {
    setStop(null);
    // The missions follow a look-around seen to its end, or left: they are how to go on.
    if (!guest) remember((before) => ({ ...before, missions: true }));
  }

  const tour = useMemo(
    () => ({
      available: enabled,
      offering: enabled && !memory.offered,
      start,
      decline,
      mark,
      pageTour: enabled && page !== null,
      startPage,
    }),
    [enabled, memory.offered, start, decline, mark, page, startPage],
  );
  const lookingAround = stop !== null ? (STOPS[stop] as Stop) : null;
  const pageStop = paging && page ? paging.stops[paging.at] : undefined;
  const pageTexts: Partial<Record<PageAnchor, PageText>> = page ? PAGE_TEXTS[page] : {};
  const pageText = pageStop ? pageTexts[pageStop] : undefined;

  return (
    <TourContext value={tour}>
      {children}
      {listing && stop === null && !paging && (
        <MissionsPanel
          missions={MISSIONS}
          done={done}
          onShow={(mission) => {
            if (mission.id === "palette" && mission.target)
              setPointed({ id: "palette", target: mission.target });
          }}
          onClose={() => remember((before) => ({ ...before, missions: false }))}
          onTourPage={tour.pageTour ? startPage : undefined}
        />
      )}
      {enabled && stop !== null && lookingAround && (
        <Spotlight
          id={lookingAround.id}
          title={t(`tour.stops.${stopText(lookingAround, guest)}.title`)}
          text={t(`tour.stops.${stopText(lookingAround, guest)}.text`)}
          target={lookingAround.target}
          position={{ at: stop + 1, of: STOPS.length }}
          onBack={stop > 0 ? () => setStop(stop - 1) : undefined}
          onNext={stop < STOPS.length - 1 ? () => setStop(stop + 1) : undefined}
          onLeave={leave}
        />
      )}
      {enabled && stop === null && !paging && pointed && (
        <Spotlight
          id={pointed.id}
          title={t(`tour.stops.${pointed.id}.title`)}
          text={t(`tour.stops.${pointed.id}.text`)}
          target={pointed.target}
          onLeave={() => setPointed(null)}
        />
      )}
      {enabled && paging && page && pageStop && (
        <Spotlight
          id={`${page}-${pageStop}`}
          title={t(`tour.anchors.${pageStop}`)}
          text={pageText ? t(pageText) : ""}
          target={PAGE_ANCHORS[pageStop]}
          position={{ at: paging.at + 1, of: paging.stops.length }}
          onBack={paging.at > 0 ? () => setPaging({ ...paging, at: paging.at - 1 }) : undefined}
          onNext={
            paging.at < paging.stops.length - 1
              ? () => setPaging({ ...paging, at: paging.at + 1 })
              : undefined
          }
          onLeave={() => setPaging(null)}
        />
      )}
    </TourContext>
  );
}

/** A guest is welcomed to a demo bench, not to an empty one. */
function stopText(stop: Stop, guest: boolean) {
  return stop.id === "welcome" && guest ? ("welcomeGuest" as const) : stop.id;
}

/**
 * What each page's tour says at each of its stops, spelled out so a missing text is a type
 * error and not an empty card.
 */
const PAGE_TEXTS = {
  parts: {
    actions: "tour.pages.parts.actions",
    filters: "tour.pages.parts.filters",
    pages: "tour.pages.parts.pages",
    list: "tour.pages.parts.list",
  },
  categories: {
    actions: "tour.pages.categories.actions",
    tree: "tour.pages.categories.tree",
    detail: "tour.pages.categories.detail",
  },
  locations: {
    actions: "tour.pages.locations.actions",
    tree: "tour.pages.locations.tree",
    detail: "tour.pages.locations.detail",
  },
  units: {
    filters: "tour.pages.units.filters",
    pages: "tour.pages.units.pages",
    list: "tour.pages.units.list",
  },
  projects: {
    actions: "tour.pages.projects.actions",
    filters: "tour.pages.projects.filters",
    pages: "tour.pages.projects.pages",
    list: "tour.pages.projects.list",
  },
  firmware: {
    actions: "tour.pages.firmware.actions",
    filters: "tour.pages.firmware.filters",
    pages: "tour.pages.firmware.pages",
    list: "tour.pages.firmware.list",
  },
  activity: {
    filters: "tour.pages.activity.filters",
    pages: "tour.pages.activity.pages",
    list: "tour.pages.activity.list",
  },
  trash: {
    filters: "tour.pages.trash.filters",
    pages: "tour.pages.trash.pages",
    list: "tour.pages.trash.list",
  },
} as const satisfies Record<TourPage, Partial<Record<PageAnchor, string>>>;

/** Any of the texts above: what a page's tour may say. */
type PageText = {
  [Page in TourPage]: (typeof PAGE_TEXTS)[Page][keyof (typeof PAGE_TEXTS)[Page]];
}[TourPage];

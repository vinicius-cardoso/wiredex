import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { benchCountsQuery } from "../dashboard/dashboard";
import { MissionsPanel } from "./MissionsPanel";
import { Spotlight } from "./Spotlight";
import {
  MISSIONS,
  type Mission,
  missionsDone,
  readMemory,
  STOPS,
  type Stop,
  type TourMemory,
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
};

const NO_TOUR: Tour = {
  available: false,
  offering: false,
  start: () => {},
  decline: () => {},
  mark: () => {},
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
 * ticks soon after it is done, whichever page it was done on.
 */
export function TourProvider({ children, enabled, guest }: Props) {
  const [memory, setMemory] = useState<TourMemory>(readMemory);
  const [stop, setStop] = useState<number | null>(null);
  // One thing pointed at by a mission's *Show me*, outside the look-around.
  const [pointed, setPointed] = useState<Stop | null>(null);

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

  // Signing out ends whatever was on screen.
  useEffect(() => {
    if (!enabled) {
      setStop(null);
      setPointed(null);
    }
  }, [enabled]);

  function leave() {
    setStop(null);
    // The missions follow a look-around seen to its end, or left: they are how to go on.
    if (!guest) remember((before) => ({ ...before, missions: true }));
  }

  const tour = useMemo(
    () => ({ available: enabled, offering: enabled && !memory.offered, start, decline, mark }),
    [enabled, memory.offered, start, decline, mark],
  );

  return (
    <TourContext value={tour}>
      {children}
      {listing && stop === null && (
        <MissionsPanel
          missions={MISSIONS}
          done={done}
          onShow={(mission) => {
            if (mission.id === "palette" && mission.target)
              setPointed({ id: "palette", target: mission.target });
          }}
          onClose={() => remember((before) => ({ ...before, missions: false }))}
        />
      )}
      {enabled && stop !== null && (
        <Spotlight
          stop={STOPS[stop] as Stop}
          position={{ at: stop + 1, of: STOPS.length }}
          onBack={stop > 0 ? () => setStop(stop - 1) : undefined}
          onNext={stop < STOPS.length - 1 ? () => setStop(stop + 1) : undefined}
          onLeave={leave}
          guest={guest}
        />
      )}
      {enabled && stop === null && pointed && (
        <Spotlight stop={pointed} onLeave={() => setPointed(null)} guest={guest} />
      )}
    </TourContext>
  );
}

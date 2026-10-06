import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Stop } from "./tour";

type Props = {
  stop: Stop;
  /** Where this stop is in the look-around; absent for a single thing pointed at. */
  position?: { at: number; of: number } | undefined;
  onBack?: (() => void) | undefined;
  onNext?: (() => void) | undefined;
  onLeave: () => void;
  guest: boolean;
};

type Box = { top: number; left: number; width: number; height: number };

const CARD_WIDTH = 320;
const GAP = 12;
const button = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

/**
 * One stop of the tour: the page dims, what the stop points at stays lit inside a ring, and a
 * card beside it says what it is. The card is a dialog, so the keyboard stays in it: Escape
 * leaves the tour, and the arrow keys step through it as *Back* and *Next* do. A stop with
 * nothing to point at, or whose target isn't on this page, puts the card in the middle.
 */
export function Spotlight({ stop, position, onBack, onNext, onLeave, guest }: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const textId = useId();
  const forward = useRef<HTMLButtonElement>(null);
  const [box, setBox] = useState<Box | null>(null);

  // Where the target is now, and again whenever the window or anything in it moves.
  useLayoutEffect(() => {
    function measure() {
      const target = stop.target ? document.querySelector(stop.target) : null;
      if (!target) return setBox(null);
      const { top, left, width, height } = target.getBoundingClientRect();
      setBox({ top: top - 4, left: left - 4, width: width + 8, height: height + 8 });
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [stop]);

  // Each stop starts on its way forward, so Enter walks the whole tour. The stop's id is read
  // so a new stop takes the focus again.
  useEffect(() => {
    forward.current?.focus();
    return () => void stop.id;
  }, [stop.id]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onLeave();
      else if (event.key === "ArrowRight") onNext?.();
      else if (event.key === "ArrowLeft") onBack?.();
      else return;
      event.preventDefault();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onBack, onNext, onLeave]);

  // Under the target when there is room, above it otherwise, and never off the screen's side.
  const below = box ? box.top + box.height + GAP : 0;
  const place = box
    ? {
        left: Math.max(8, Math.min(box.left, window.innerWidth - CARD_WIDTH - 8)),
        ...(below + 180 < window.innerHeight || box.top < 200
          ? { top: below }
          : { bottom: window.innerHeight - box.top + GAP }),
      }
    : { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  const last = !onNext;
  const text = stop.id === "welcome" && guest ? ("welcomeGuest" as const) : stop.id;

  return (
    <div className="fixed inset-0 z-40">
      {/* Clicking the dimmed page leaves the tour, as Escape does. */}
      <button
        type="button"
        aria-label={t("tour.leave")}
        tabIndex={-1}
        onClick={onLeave}
        className={`absolute inset-0 cursor-default ${box ? "" : "bg-black/55"}`}
      />
      {box && (
        // The ring's wide shadow is what dims the rest of the page around the target.
        <div
          aria-hidden="true"
          style={box}
          className="pointer-events-none absolute rounded-md ring-2 ring-primary shadow-[0_0_0_9999px_rgb(0_0_0/0.55)]"
        />
      )}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={textId}
        style={{ ...place, width: CARD_WIDTH }}
        className="absolute grid max-w-[calc(100vw-1rem)] gap-2 rounded-lg border border-border-strong bg-surface p-4 shadow-lg"
      >
        <h2 id={titleId} className="font-display text-lg font-semibold">
          {t(`tour.stops.${text}.title`)}
        </h2>
        <p id={textId} className="text-sm text-muted">
          {t(`tour.stops.${text}.text`)}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <span className="text-xs text-muted">
            {position && t("tour.position", { at: position.at, of: position.of })}
          </span>
          <div className="flex flex-wrap gap-2">
            {position && !last && (
              <button type="button" onClick={onLeave} className={button}>
                {t("tour.skip")}
              </button>
            )}
            {onBack && (
              <button type="button" onClick={onBack} className={button}>
                {t("tour.back")}
              </button>
            )}
            <button
              ref={forward}
              type="button"
              onClick={onNext ?? onLeave}
              className="rounded-md bg-primary px-3 py-1 text-sm font-semibold text-on-primary hover:opacity-90"
            >
              {t(last ? (position ? "tour.finish" : "tour.gotIt") : "tour.next")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

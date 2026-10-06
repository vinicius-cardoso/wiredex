import { Link } from "@tanstack/react-router";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { Mission } from "./tour";

type Props = {
  missions: readonly Mission[];
  done: ReadonlySet<Mission["id"]>;
  /** Points at a mission's target when it has no page of its own to open. */
  onShow: (mission: Mission) => void;
  onClose: () => void;
};

const link = "text-xs text-primary hover:underline";

/**
 * The first things to do, in a corner of every page: each with how far along the list is, a
 * tick once it is done, and a way to where it is done. It never covers the page's own work, and
 * closes for good from its button; the account menu brings the tour back.
 */
export function MissionsPanel({ missions, done, onShow, onClose }: Props) {
  const { t } = useTranslation();
  const headingId = useId();
  const count = missions.filter((mission) => done.has(mission.id)).length;
  const complete = count === missions.length;

  return (
    <aside
      aria-labelledby={headingId}
      className="fixed right-4 bottom-10 z-30 grid w-80 max-w-[calc(100vw-2rem)] gap-2 rounded-lg border border-border-strong bg-surface p-4 shadow-lg"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={headingId} className="font-display text-base font-semibold">
          {t("tour.missions.title")}
        </h2>
        <button type="button" onClick={onClose} className="text-xs text-muted hover:underline">
          {t("tour.missions.close")}
        </button>
      </div>
      {/* Announced as it changes, so a tick earned on another page is heard. */}
      <p role="status" className="text-sm text-muted">
        {complete
          ? t("tour.missions.complete")
          : t("tour.missions.progress", { done: count, of: missions.length })}
      </p>
      <div
        role="progressbar"
        aria-label={t("tour.missions.title")}
        aria-valuemin={0}
        aria-valuemax={missions.length}
        aria-valuenow={count}
        className="h-1.5 overflow-hidden rounded-full bg-surface-2"
      >
        <div
          className="h-full bg-primary"
          style={{ width: `${(count / missions.length) * 100}%` }}
        />
      </div>
      <ul className="grid gap-2 pt-1">
        {missions.map((mission) => {
          const ticked = done.has(mission.id);
          return (
            <li key={mission.id} className="flex items-start gap-2 text-sm">
              <span
                aria-hidden="true"
                className={`mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full border text-[10px] ${
                  ticked ? "border-ok bg-ok text-bg" : "border-border-strong"
                }`}
              >
                {ticked && "✓"}
              </span>
              <span className="grid min-w-0 gap-0.5">
                <span className={ticked ? "text-muted line-through" : ""}>
                  {t(`tour.missions.${mission.id}`)}
                  <span className="sr-only">
                    {" "}
                    {t(ticked ? "tour.missions.done" : "tour.missions.toDo")}
                  </span>
                </span>
                {!ticked &&
                  (mission.to ? (
                    <Link to={mission.to} className={link}>
                      {t("tour.missions.go")}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onShow(mission)}
                      className={`${link} justify-self-start`}
                    >
                      {t("tour.missions.show")}
                    </button>
                  ))}
              </span>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

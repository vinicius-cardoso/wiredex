import { useNavigate } from "@tanstack/react-router";
import type { SessionInfo } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { recogniseDevice } from "./device";
import { useRevokeSession, useSessions } from "./sessions";

export function SessionsPage() {
  const { t } = useTranslation();
  const sessions = useSessions();
  const revoke = useRevokeSession();

  return (
    <section className="grid max-w-3xl gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{t("sessions.title")}</h1>
      <p className="text-muted">{t("sessions.intro")}</p>
      {sessions.isPending && <p className="text-muted">{t("sessions.loading")}</p>}
      {sessions.isError && (
        <p role="alert" className="text-crit">
          {t("sessions.error")}
        </p>
      )}
      {revoke.isError && (
        <p role="alert" className="text-crit">
          {t("sessions.revokeError")}
        </p>
      )}
      {sessions.data && (
        <ul className="grid gap-3">
          {sessions.data.map((session) => (
            <SessionRow key={session.id} session={session} revoke={revoke} />
          ))}
        </ul>
      )}
    </section>
  );
}

type RowProps = { session: SessionInfo; revoke: ReturnType<typeof useRevokeSession> };

function SessionRow({ session, revoke }: RowProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const device = useDeviceName(session.device);
  const formatDate = useDateFormat();

  async function logOut() {
    await revoke.mutateAsync(session);
    if (session.current) await navigate({ to: "/login" });
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="grid gap-1">
        <p className="flex flex-wrap items-center gap-2 font-medium" title={session.device}>
          {device}
          {session.current && (
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-primary">
              {t("sessions.thisDevice")}
            </span>
          )}
        </p>
        <p className="text-sm text-muted">
          {t("sessions.lastActive", { date: formatDate(session.last_seen_at) })} ·{" "}
          {t("sessions.loggedIn", { date: formatDate(session.created_at) })}
        </p>
      </div>
      <button
        type="button"
        onClick={() => logOut().catch(() => {})}
        disabled={revoke.isPending}
        aria-label={t("sessions.logOutDevice", { device })}
        className="rounded-md border border-border-strong px-3 py-1 text-sm hover:bg-surface-2 disabled:opacity-60"
      >
        {t("sessions.logOut")}
      </button>
    </li>
  );
}

/** "Firefox on Linux" for browsers we know; the raw User-Agent for anything else. */
function useDeviceName(userAgent: string): string {
  const { t } = useTranslation();
  const device = recogniseDevice(userAgent);
  if (device) return t("sessions.on", device);
  return userAgent || t("sessions.unknownDevice");
}

function useDateFormat(): (iso: string) => string {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (iso) => format.format(new Date(iso));
}

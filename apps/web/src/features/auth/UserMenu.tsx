import { Link, useNavigate } from "@tanstack/react-router";
import type { UserInfo } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { useLogOut } from "./auth";

export function UserMenu({ user }: { user: UserInfo }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const logOut = useLogOut();

  async function leave() {
    try {
      await logOut.mutateAsync();
    } finally {
      // Logged out here even if the server couldn't be told: useLogOut forgot the user.
      await navigate({ to: "/login" });
    }
  }

  return (
    <section aria-label={t("account.label")} className="flex items-center gap-3 text-sm">
      <span className="font-medium" title={user.email}>
        {user.name}
      </span>
      {user.expires_at && (
        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-accent-ink dark:text-accent">
          {t("account.guestUntil", {
            date: new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(
              new Date(user.expires_at),
            ),
          })}
        </span>
      )}
      <Link
        to="/sessions"
        className="text-muted underline-offset-4 hover:underline data-[status=active]:font-semibold data-[status=active]:text-primary"
      >
        {t("account.devices")}
      </Link>
      <button
        type="button"
        onClick={leave}
        disabled={logOut.isPending}
        className="rounded-md border border-border-strong px-3 py-1 hover:bg-surface-2 disabled:opacity-60"
      >
        {t("account.logOut")}
      </button>
    </section>
  );
}

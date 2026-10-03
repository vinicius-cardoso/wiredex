import { Link, useNavigate } from "@tanstack/react-router";
import type { UserInfo } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { DevicesIcon, iconButton, LogOutIcon } from "../../shared/ui/icons";
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
    <section aria-label={t("account.label")} className="flex items-center gap-2 text-sm">
      {/* The circle is for the eye; the name itself stays for a screen reader. */}
      <span
        aria-hidden="true"
        title={`${user.name} · ${user.email}`}
        className="inline-flex h-8 min-w-8 items-center justify-center rounded-full bg-primary px-1 text-xs font-semibold text-on-primary"
      >
        {initials(user.name)}
      </span>
      <span className="sr-only">{user.name}</span>
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
        aria-label={t("account.devices")}
        title={t("account.devices")}
        className={`${iconButton} data-[status=active]:border-primary data-[status=active]:text-primary`}
      >
        <DevicesIcon />
      </Link>
      <button
        type="button"
        aria-label={t("account.logOut")}
        title={t("account.logOut")}
        onClick={leave}
        disabled={logOut.isPending}
        className={`${iconButton} disabled:opacity-60`}
      >
        <LogOutIcon />
      </button>
    </section>
  );
}

/**
 * A name as the avatar shows it: the first letter of its first word and of its last, or one
 * letter for a single word. "Vinícius Cardoso" is VC, and "Vinicius" is V.
 */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words.at(-1)?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

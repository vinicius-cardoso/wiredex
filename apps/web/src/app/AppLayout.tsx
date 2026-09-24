import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../features/auth/auth";
import { UserMenu } from "../features/auth/UserMenu";
import { VersionBadge } from "../features/system/VersionBadge";
import { LanguageSwitcher } from "../shared/i18n/LanguageSwitcher";
import { ThemeSwitcher } from "../shared/theme/ThemeSwitcher";
import { Logo } from "./Logo";

export function AppLayout() {
  const { t } = useTranslation();
  const { data: user } = useCurrentUser();

  return (
    <div className="grid min-h-dvh grid-rows-[auto_1fr_auto]">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2 font-display text-lg font-bold">
            <Logo />
            {t("app.name")}
          </Link>
          {user && (
            <nav aria-label={t("nav.label")} className="flex gap-1 text-sm">
              <Link
                to="/"
                className="rounded-md px-3 py-1.5 text-muted hover:bg-surface-2 data-[status=active]:bg-surface-2 data-[status=active]:font-semibold data-[status=active]:text-primary"
              >
                {t("nav.dashboard")}
              </Link>
            </nav>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <ThemeSwitcher />
            <LanguageSwitcher />
            {user && <UserMenu user={user} />}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 py-3">
          <VersionBadge />
        </div>
      </footer>
    </div>
  );
}

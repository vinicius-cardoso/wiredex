import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../features/auth/auth";
import { UserMenu } from "../features/auth/UserMenu";
import { QuickAddProvider, useQuickAdd } from "../features/inventory/intake/QuickAddProvider";
import { VersionBadge } from "../features/system/VersionBadge";
import { LanguageSwitcher } from "../shared/i18n/LanguageSwitcher";
import { ThemeSwitcher } from "../shared/theme/ThemeSwitcher";
import { Logo } from "./Logo";

const navLink =
  "rounded-md px-3 py-1.5 text-muted hover:bg-surface-2 data-[status=active]:bg-surface-2 data-[status=active]:font-semibold data-[status=active]:text-primary";

export function AppLayout() {
  const { t } = useTranslation();
  const { data: user } = useCurrentUser();

  return (
    // Quick-add is for the signed-in app only: nobody signed in, no button and no Alt+N.
    <QuickAddProvider enabled={Boolean(user)}>
      <div className="grid min-h-dvh grid-rows-[auto_1fr_auto]">
        <header className="border-b border-border bg-surface">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
            <Link to="/" className="flex items-center gap-2 font-display text-lg font-bold">
              <Logo />
              {t("app.name")}
            </Link>
            {user && (
              <nav aria-label={t("nav.label")} className="flex gap-1 text-sm">
                <Link to="/" className={navLink}>
                  {t("nav.dashboard")}
                </Link>
                <Link to="/parts" className={navLink}>
                  {t("nav.parts")}
                </Link>
                <Link to="/categories" className={navLink}>
                  {t("nav.categories")}
                </Link>
                <Link to="/locations" className={navLink}>
                  {t("nav.locations")}
                </Link>
                <Link to="/units" className={navLink}>
                  {t("nav.units")}
                </Link>
              </nav>
            )}
            <div className="ml-auto flex flex-wrap items-center gap-3">
              {user && <QuickAddButton />}
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
    </QuickAddProvider>
  );
}

/**
 * Quick-add from every page (requirement 2.1). The shortcut is shown on the button and
 * announced through `aria-keyshortcuts`, so the visible hint stays out of the button's name.
 */
function QuickAddButton() {
  const { t } = useTranslation();
  const quickAdd = useQuickAdd();

  return (
    <button
      type="button"
      aria-keyshortcuts="Alt+N"
      onClick={() => quickAdd.open()}
      className="flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90"
    >
      {t("inventory.quickAdd.open")}
      <span aria-hidden="true">
        <kbd className="rounded border border-on-primary/50 px-1 font-mono text-xs font-normal">
          {t("inventory.quickAdd.shortcut")}
        </kbd>
      </span>
    </button>
  );
}

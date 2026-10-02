import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../features/auth/auth";
import { UserMenu } from "../features/auth/UserMenu";
import { QuickAddProvider, useQuickAdd } from "../features/inventory/intake/QuickAddProvider";
import { isMac, PaletteProvider, usePalette } from "../features/palette/PaletteProvider";
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
    // Quick-add and the palette are for the signed-in app only: nobody signed in, no buttons,
    // no Alt+N and no Ctrl+K. The palette sits inside quick-add, so its command can open it.
    <QuickAddProvider enabled={Boolean(user)}>
      <PaletteProvider enabled={Boolean(user)}>
        <div className="grid min-h-dvh grid-rows-[auto_1fr_auto]">
          <header className="border-b border-border bg-surface">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
              <Link to="/" className="flex items-center gap-2 font-display text-lg font-bold">
                <Logo />
                {t("app.name")}
              </Link>
              {user && (
                <nav aria-label={t("nav.label")} className="flex flex-wrap gap-1 text-sm">
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
                  <Link to="/projects" className={navLink}>
                    {t("nav.projects")}
                  </Link>
                  <Link to="/firmware" className={navLink}>
                    {t("nav.firmware")}
                  </Link>
                  <Link to="/activity" className={navLink}>
                    {t("nav.activity")}
                  </Link>
                  {/* Last: where a deleted record waits, one click from anywhere (16's 9.2). */}
                  <Link to="/trash" className={navLink}>
                    {t("nav.trash")}
                  </Link>
                </nav>
              )}
              <div className="ml-auto flex flex-wrap items-center gap-3">
                {user && <SearchButton />}
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
      </PaletteProvider>
    </QuickAddProvider>
  );
}

/**
 * The palette from every page (19's requirement 3.2). The chord is shown on the button, Ctrl K or
 * ⌘ K as the platform has it, and announced through `aria-keyshortcuts`, so the hint stays out of
 * the button's name.
 */
function SearchButton() {
  const { t } = useTranslation();
  const palette = usePalette();

  return (
    <button
      type="button"
      aria-keyshortcuts="Control+K Meta+K"
      onClick={() => palette.open()}
      className="flex items-center gap-2 rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
    >
      {t("palette.open")}
      <span aria-hidden="true">
        <kbd className="rounded border border-border-strong px-1 font-mono text-xs text-muted">
          {t(isMac() ? "palette.shortcutMac" : "palette.shortcut")}
        </kbd>
      </span>
    </button>
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

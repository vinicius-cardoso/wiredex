import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../features/auth/auth";
import { UserMenu } from "../features/auth/UserMenu";
import { QuickAddProvider, useQuickAdd } from "../features/inventory/intake/QuickAddProvider";
import { isMac, PaletteProvider, usePalette } from "../features/palette/PaletteProvider";
import { VersionBadge } from "../features/system/VersionBadge";
import { LanguageSwitcher } from "../shared/i18n/LanguageSwitcher";
import { ThemeSwitcher } from "../shared/theme/ThemeSwitcher";
import { iconButton, PlusIcon, SearchIcon } from "../shared/ui/icons";
import { Logo } from "./Logo";

const navLink =
  "rounded-md px-2 py-1.5 text-muted hover:bg-surface-2 data-[status=active]:bg-surface-2 data-[status=active]:font-semibold data-[status=active]:text-primary";

export function AppLayout() {
  const { t } = useTranslation();
  const { data: user } = useCurrentUser();

  return (
    // Quick-add and the palette are for the signed-in app only: nobody signed in, no buttons,
    // no Alt+N and no Ctrl+K. The palette sits inside quick-add, so its command can open it.
    <QuickAddProvider enabled={Boolean(user)}>
      <PaletteProvider enabled={Boolean(user)}>
        {/* On a laptop the shell is the screen: the header and footer stay put and the main
            area scrolls, so a list can take exactly the height that is left. The one column
            is never wider than the screen, whatever a table's own width: a wide table
            scrolls inside its frame, and on a phone the page never scrolls sideways. */}
        <div className="grid min-h-dvh grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr_auto] lg:h-dvh">
          <header className="border-b border-border bg-surface">
            <div className="mx-auto flex max-w-[110rem] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 lg:px-6">
              <Link to="/" className="flex items-center gap-2 font-display text-lg font-bold">
                <Logo />
                {t("app.name")}
              </Link>
              {user && (
                <nav aria-label={t("nav.label")} className="flex flex-wrap gap-0.5 text-sm">
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
              <div className="ml-auto flex flex-wrap items-center gap-2">
                {user && <SearchButton />}
                {user && <QuickAddButton />}
                <ThemeSwitcher />
                <LanguageSwitcher />
                {user && <UserMenu user={user} />}
              </div>
            </div>
          </header>

          <main className="lg:min-h-0 lg:overflow-y-auto">
            <div className="mx-auto w-full max-w-[110rem] px-4 py-5 lg:h-full lg:px-6">
              <Outlet />
            </div>
          </main>

          <footer className="border-t border-border">
            <div className="mx-auto max-w-[110rem] px-4 py-1.5 lg:px-6">
              <VersionBadge />
            </div>
          </footer>
        </div>
      </PaletteProvider>
    </QuickAddProvider>
  );
}

/**
 * The palette from every page (19's requirement 3.2), as an icon so the header stays on one
 * line. The chord, Ctrl K or ⌘ K as the platform has it, is in the tooltip and announced
 * through `aria-keyshortcuts`, so it stays out of the button's name.
 */
function SearchButton() {
  const { t } = useTranslation();
  const palette = usePalette();
  const chord = t(isMac() ? "palette.shortcutMac" : "palette.shortcut");

  return (
    <button
      type="button"
      aria-label={t("palette.open")}
      aria-keyshortcuts="Control+K Meta+K"
      title={`${t("palette.open")} (${chord})`}
      onClick={() => palette.open()}
      className={iconButton}
    >
      <SearchIcon />
    </button>
  );
}

/**
 * Quick-add from every page (requirement 2.1), as a plus in the primary colour. The shortcut
 * is in the tooltip and announced through `aria-keyshortcuts`, so it stays out of the
 * button's name.
 */
function QuickAddButton() {
  const { t } = useTranslation();
  const quickAdd = useQuickAdd();

  return (
    <button
      type="button"
      aria-label={t("inventory.quickAdd.open")}
      aria-keyshortcuts="Alt+N"
      title={`${t("inventory.quickAdd.open")} (${t("inventory.quickAdd.shortcut")})`}
      onClick={() => quickAdd.open()}
      className="inline-flex h-8 min-w-8 items-center justify-center rounded-md bg-primary text-on-primary hover:opacity-90"
    >
      <PlusIcon />
    </button>
  );
}

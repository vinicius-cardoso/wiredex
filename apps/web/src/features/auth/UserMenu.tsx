import { Link, useNavigate } from "@tanstack/react-router";
import type { UserInfo } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DevicesIcon, LogOutIcon } from "../../shared/ui/icons";
import { useLogOut } from "./auth";

export function UserMenu({ user }: { user: UserInfo }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const logOut = useLogOut();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const container = useRef<HTMLDivElement | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);

  // A click anywhere else shuts the menu; Escape shuts it and hands focus back to its button.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function leave() {
    setOpen(false);
    try {
      await logOut.mutateAsync();
    } finally {
      // Logged out here even if the server couldn't be told: useLogOut forgot the user.
      await navigate({ to: "/login" });
    }
  }

  return (
    <section aria-label={t("account.label")} className="flex items-center gap-2 text-sm">
      {user.expires_at && (
        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-accent-ink dark:text-accent">
          {t("account.guestUntil", {
            date: new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(
              new Date(user.expires_at),
            ),
          })}
        </span>
      )}
      <div ref={container} className="relative">
        <button
          ref={button}
          type="button"
          aria-label={t("account.menu", { name: user.name })}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          title={user.name}
          onClick={() => setOpen((shown) => !shown)}
          className="inline-flex h-8 min-w-8 items-center justify-center rounded-full bg-primary px-1 text-xs font-semibold text-on-primary hover:opacity-90"
        >
          {initials(user.name)}
        </button>
        {open && (
          <div
            id={menuId}
            role="menu"
            aria-label={t("account.label")}
            className="absolute right-0 z-20 mt-2 grid w-56 gap-1 rounded-lg border border-border bg-surface p-2 shadow-lg"
          >
            <div className="border-b border-border px-2 pb-2">
              <p className="truncate font-medium">{user.name}</p>
              <p className="truncate text-xs text-muted">{user.email}</p>
            </div>
            <Link
              to="/sessions"
              role="menuitem"
              onClick={() => setOpen(false)}
              className={`${menuItem} data-[status=active]:font-semibold data-[status=active]:text-primary`}
            >
              <DevicesIcon />
              {t("account.devices")}
            </Link>
            <button
              type="button"
              role="menuitem"
              onClick={leave}
              disabled={logOut.isPending}
              className={`${menuItem} disabled:opacity-60`}
            >
              <LogOutIcon />
              {t("account.logOut")}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

const menuItem =
  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-text hover:bg-surface-2";

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

import { useNavigate } from "@tanstack/react-router";
import type { UserInfo } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { useLogOut } from "./auth";

export function UserMenu({ user }: { user: UserInfo }) {
  const { t } = useTranslation();
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

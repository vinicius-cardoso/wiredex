import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useReorderList } from "./reorder";

/**
 * The dashboard's line about the reorder list: how many parts are below their minimum, linking
 * to them. Nothing while there are none, or while the list can't be read: the dashboard's own
 * panels never wait on it.
 */
export function ReorderNotice() {
  const { t } = useTranslation();
  const count = useReorderList().data?.items.length ?? 0;
  if (count === 0) return null;

  return (
    <p className="rounded-lg border border-warn bg-surface px-4 py-3">
      {t("reorder.notice", { count })}{" "}
      <Link to="/reorder" className="font-semibold text-primary hover:underline">
        {t("reorder.open")}
      </Link>
    </p>
  );
}

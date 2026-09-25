import { useTranslation } from "react-i18next";
import { type CategoryBranch, categoryTree, useCategories } from "./catalog";

export function CategoriesPage() {
  const { t } = useTranslation();
  const categories = useCategories();
  const roots = categoryTree(categories.data ?? []);

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {t("catalog.categories.title")}
      </h1>
      <p className="text-muted">{t("catalog.categories.intro")}</p>

      {categories.isPending && <p className="text-muted">{t("catalog.categories.loading")}</p>}
      {categories.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.categories.error")}
        </p>
      )}
      {categories.data && roots.length === 0 && (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {t("catalog.categories.empty")}
        </p>
      )}
      {roots.length > 0 && <Branches branches={roots} label={t("catalog.categories.tree")} />}
    </section>
  );
}

type Props = { branches: CategoryBranch[]; label?: string };

function Branches({ branches, label }: Props) {
  const { t } = useTranslation();

  return (
    <ul className="grid gap-2" {...(label ? { "aria-label": label } : {})}>
      {branches.map(({ category, children }) => (
        <li key={category.id} className="grid gap-2">
          <div className="flex flex-wrap items-baseline gap-x-3 rounded-lg border border-border bg-surface px-4 py-2">
            <span className="font-medium">{category.name}</span>
            <span className="text-sm text-muted">
              {t("catalog.categories.counts", {
                children: category.child_count,
                parts: category.part_count,
              })}
            </span>
          </div>
          {children.length > 0 && (
            <div className="border-l border-border pl-4">
              <Branches branches={children} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

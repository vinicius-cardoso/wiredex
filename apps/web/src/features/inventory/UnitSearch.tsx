import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useUnitSearch } from "./units";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

/**
 * A workspace-wide unit search over code, serial and MAC (requirement 8.4). The term is a
 * case-insensitive substring the API matches; each hit links to the unit's page.
 */
export function UnitSearch() {
  const { t } = useTranslation();
  const searchId = useId();
  const [term, setTerm] = useState("");
  const results = useUnitSearch(term);
  const blank = t("inventory.units.blank");
  const searching = term.trim() !== "";

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">
        {t("inventory.units.search.title")}
      </h1>
      <p className="text-muted">{t("inventory.units.search.intro")}</p>

      <div className="grid max-w-md gap-1">
        <label htmlFor={searchId} className="text-sm font-medium">
          {t("inventory.units.search.label")}
        </label>
        <input
          id={searchId}
          type="search"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder={t("inventory.units.search.placeholder")}
          className={control}
        />
      </div>

      {!searching && <p className="text-muted">{t("inventory.units.search.prompt")}</p>}
      {searching && results.isPending && (
        <p className="text-muted">{t("inventory.units.loading")}</p>
      )}
      {searching && results.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.units.error")}
        </p>
      )}
      {searching &&
        results.data &&
        (results.data.length === 0 ? (
          <p className="text-muted">{t("inventory.units.search.empty")}</p>
        ) : (
          <table className="w-full max-w-2xl border-collapse text-left text-sm">
            <caption className="sr-only">{t("inventory.units.list")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.codeColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.serialColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.macColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.statusColumn")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("inventory.units.locationColumn")}
                </th>
              </tr>
            </thead>
            <tbody>
              {results.data.map((unit) => (
                <tr key={unit.id} className="border-b border-border">
                  <th scope="row" className="py-2 pr-4 font-normal">
                    <Link
                      to="/units/$unitId"
                      params={{ unitId: unit.id }}
                      className="font-mono text-primary hover:underline"
                    >
                      {unit.code}
                    </Link>
                  </th>
                  <td className="py-2 pr-4">{unit.serial ?? blank}</td>
                  <td className="py-2 pr-4 font-mono">{unit.mac ?? blank}</td>
                  <td className="py-2 pr-4">{t(`inventory.units.status.${unit.status}`)}</td>
                  <td className="py-2">{unit.location ? unit.location.name : blank}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </section>
  );
}

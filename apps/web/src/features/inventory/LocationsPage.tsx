import { getRouteApi, Link } from "@tanstack/react-router";
import type { LocationNode } from "@wiredex/api-client";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FilterField,
  filterButton,
  filterControl,
  listCell,
  listHead,
  listHeadCell,
  listPage,
  listRow,
  listTable,
  PageHeader,
  primaryAction,
  secondaryAction,
} from "../../shared/ui/list";
import { keptWithAncestors, type TreeBranch, TreeFrame, TreeView } from "../../shared/ui/tree";
import {
  type LocationBranch,
  locationTree,
  matchesLocation,
  refusalMessage,
  useCreateLocation,
  useDeleteLocation,
  useEditLocation,
  useLocationStock,
  useLocations,
} from "./inventory";
import { useUnitsOfLocation } from "./units";

const route = getRouteApi("/authenticated/locations");

/**
 * The location tree and the location picked in it, side by side: on the left a compact tree,
 * one line per location with its short code and how many lots it holds, narrowed by a filter
 * over names and codes that keeps a match's ancestors in view (requirement 9.1); on the right
 * the picked location with its rename, move and delete, and what it holds: its lots and its
 * boards. The header adds a location inside the picked one, or at the top level while none is
 * picked. On a laptop each side scrolls on its own.
 */
export function LocationsPage() {
  const { t } = useTranslation();
  const filterId = useId();
  const locations = useLocations();
  // A location named in the address opens selected, as the palette sends one (19's 5.4); the
  // tree's own clicks select without touching the address.
  const { selected: named } = route.useSearch();
  const [selectedId, setSelectedId] = useState<string | null>(named ?? null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (named) setSelectedId(named);
  }, [named]);

  const all = locations.data ?? [];
  const selected = all.find((location) => location.id === selectedId) ?? null;
  const shown = keptWithAncestors(
    all,
    (location) => matchesLocation(location, filter),
    (location) => location.id,
    (location) => location.parent_id,
  );
  const roots = branchesOf(locationTree(shown));

  return (
    <section className={listPage}>
      <PageHeader
        title={t("inventory.locations.title")}
        intro={t("inventory.locations.intro")}
        actions={<NewLocationForm parent={selected} />}
      />

      {locations.isPending && <p className="text-muted">{t("inventory.locations.loading")}</p>}
      {locations.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.locations.error")}
        </p>
      )}
      {locations.data && all.length === 0 && (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {t("inventory.locations.empty")}
        </p>
      )}

      {all.length > 0 && (
        <div className="grid gap-3 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(15rem,22rem)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col gap-2">
            <FilterField label={t("inventory.locations.filter")} htmlFor={filterId}>
              <div className="flex gap-2">
                <input
                  id={filterId}
                  type="search"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder={t("inventory.locations.filterPlaceholder")}
                  className={`${filterControl} min-w-0 flex-1`}
                />
                {filter !== "" && (
                  <button type="button" onClick={() => setFilter("")} className={filterButton}>
                    {t("inventory.locations.clearFilter")}
                  </button>
                )}
              </div>
            </FilterField>
            {shown.length === 0 && (
              <p role="status" className="text-sm text-muted">
                {t("inventory.locations.filterEmpty")}
              </p>
            )}
            {shown.length > 0 && (
              <TreeFrame>
                <TreeView
                  // A new filter draws the tree afresh, so a branch folded earlier can't hide a
                  // match.
                  key={filter}
                  label={t("inventory.locations.tree")}
                  roots={roots}
                  idOf={(location) => location.id}
                  nameOf={(location) => location.name}
                  detailOf={(location) => <LocationDetail location={location} />}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </TreeFrame>
            )}
          </div>

          <div className="grid min-w-0 content-start gap-3 lg:min-h-0 lg:overflow-y-auto">
            {selected ? (
              <>
                <LocationActions
                  location={selected}
                  locations={all}
                  onDeleted={() => setSelectedId(null)}
                />
                <LocationHoldings location={selected} />
              </>
            ) : (
              <p className="text-muted">{t("inventory.locations.pickOne")}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** What sits beside a location's name: a quiet count of its lots, then its code in mono. */
function LocationDetail({ location }: { location: LocationNode }) {
  const { t } = useTranslation();
  return (
    <>
      <span title={t("inventory.locations.lotCount", { count: location.lot_count })}>
        {location.lot_count}
      </span>
      <span className="font-mono">{location.code}</span>
    </>
  );
}

/** Inventory's branches in the tree's shape. */
function branchesOf(branches: LocationBranch[]): TreeBranch<LocationNode>[] {
  return branches.map((branch) => ({
    node: branch.location,
    children: branchesOf(branch.children),
  }));
}

/**
 * The header's add: a name box and *Add*, which puts the new location inside the picked one,
 * or at the top level while none is picked. The box says where the location will go.
 */
function NewLocationForm({ parent }: { parent: LocationNode | null }) {
  const { t } = useTranslation();
  const id = useId();
  const whereId = useId();
  const [name, setName] = useState("");
  const create = useCreateLocation();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") return;
    create.mutate(
      { name: name.trim(), parent_id: parent?.id ?? null },
      { onSuccess: () => setName("") },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <label htmlFor={id} className="sr-only">
        {t("inventory.locations.add")}
      </label>
      <input
        id={id}
        type="text"
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder={
          parent
            ? t("inventory.locations.addPlaceholderUnder", { name: parent.name })
            : t("inventory.locations.addPlaceholderRoot")
        }
        aria-describedby={whereId}
        className={`${filterControl} sm:w-64`}
      />
      <span id={whereId} className="sr-only">
        {parent
          ? t("inventory.locations.addUnder", { name: parent.name })
          : t("inventory.locations.addAtRoot")}
      </span>
      <button type="submit" disabled={create.isPending} className={primaryAction}>
        {t("inventory.locations.create")}
      </button>
      {create.isError && (
        <p role="alert" className="basis-full text-sm text-crit">
          {refusalMessage(create.error) ?? t("inventory.locations.createError")}
        </p>
      )}
    </form>
  );
}

type ActionProps = {
  location: LocationNode;
  locations: LocationNode[];
  onDeleted: () => void;
};

/** Rename, move and delete for the location the tree has picked (requirements 9.1, 9.2). */
function LocationActions({ location, locations, onDeleted }: ActionProps) {
  const { t } = useTranslation();
  const nameId = useId();
  const parentId = useId();
  const edit = useEditLocation();
  const remove = useDeleteLocation();
  const [asking, setAsking] = useState(false);

  function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const named = new FormData(event.currentTarget).get("name");
    const name = String(named ?? "").trim();
    if (name === "" || name === location.name) return;
    edit.mutate({ locationId: location.id, body: { name } });
  }

  function move(parent: string) {
    edit.mutate({ locationId: location.id, body: { parent_id: parent === "" ? null : parent } });
  }

  return (
    <section
      aria-label={t("inventory.locations.selected", { name: location.name })}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="min-w-0 font-display text-xl font-semibold wrap-anywhere">
          {location.name}{" "}
          <span className="font-mono text-base font-normal text-muted">{location.code}</span>
        </h2>
        {!asking && (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="inline-flex h-9 items-center rounded-md border border-crit px-3 text-sm text-crit hover:bg-surface-2"
          >
            {t("inventory.locations.delete")}
          </button>
        )}
      </div>

      {asking && (
        <fieldset className="grid gap-2">
          <legend className="text-sm">
            {t("inventory.locations.deleteQuestion", { name: location.name })}
          </legend>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(location.id, {
                  onSuccess: () => {
                    setAsking(false);
                    onDeleted();
                  },
                })
              }
              className="inline-flex h-9 items-center rounded-md bg-crit px-3 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {t("inventory.locations.deleteConfirm")}
            </button>
            <button type="button" onClick={() => setAsking(false)} className={secondaryAction}>
              {t("inventory.locations.deleteCancel")}
            </button>
          </div>
          {/* The refusal stays here, beside the button that asked for it (requirement 9.2). */}
          {remove.isError && (
            <p role="alert" className="text-sm text-crit">
              {refusalMessage(remove.error) ?? t("inventory.locations.deleteError")}
            </p>
          )}
        </fieldset>
      )}

      <div className="grid items-start gap-x-4 gap-y-3 sm:grid-cols-2">
        <form onSubmit={rename} className="grid gap-1">
          <label htmlFor={nameId} className="text-xs font-medium text-muted">
            {t("inventory.locations.renameLabel")}
          </label>
          <div className="flex gap-2">
            <input
              id={nameId}
              name="name"
              type="text"
              defaultValue={location.name}
              // Remounts with the location, so the box always holds the selected name.
              key={location.id}
              className={filterControl}
            />
            <button type="submit" className={filterButton} disabled={edit.isPending}>
              {t("inventory.locations.rename")}
            </button>
          </div>
        </form>

        <div className="grid gap-1">
          <label htmlFor={parentId} className="text-xs font-medium text-muted">
            {t("inventory.locations.moveLabel")}
          </label>
          <select
            id={parentId}
            value={location.parent_id ?? ""}
            onChange={(event) => move(event.target.value)}
            className={filterControl}
          >
            <option value="">{t("inventory.locations.moveRoot")}</option>
            {locations
              .filter((candidate) => candidate.id !== location.id)
              .map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name} ({candidate.code})
                </option>
              ))}
          </select>
        </div>
      </div>

      {edit.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(edit.error) ?? t("inventory.locations.editError")}
        </p>
      )}
    </section>
  );
}

/**
 * What the picked location holds: its lots, each part with its on hand and reserved, and the
 * boards sitting in it. Two reads, whatever the number of rows.
 */
function LocationHoldings({ location }: { location: LocationNode }) {
  const { t } = useTranslation();
  const stock = useLocationStock(location.id);
  const boards = useUnitsOfLocation(location.id);
  const lots = stock.data ?? [];
  const units = boards.data ?? [];
  const unknown = t("inventory.boards.unknownPart");

  return (
    <section
      aria-label={t("inventory.locations.holds.title", { name: location.name })}
      className="grid gap-4 rounded-lg border border-border bg-surface p-4"
    >
      <div className="grid gap-2">
        <h2 className="font-display text-lg font-semibold">
          {t("inventory.locations.holds.stock")}
        </h2>
        {stock.isPending && (
          <p className="text-sm text-muted">{t("inventory.locations.holds.loading")}</p>
        )}
        {stock.isError && (
          <p role="alert" className="text-sm text-crit">
            {t("inventory.locations.holds.error")}
          </p>
        )}
        {stock.data && lots.length === 0 && (
          <p className="text-sm text-muted">{t("inventory.locations.holds.noStock")}</p>
        )}
        {lots.length > 0 && (
          <div className="overflow-x-auto">
            <table className={listTable}>
              <caption className="sr-only">{t("inventory.locations.holds.stock")}</caption>
              <thead className={listHead}>
                <tr>
                  <th scope="col" className={listHeadCell}>
                    {t("inventory.locations.holds.columns.part")}
                  </th>
                  <th scope="col" className={`${listHeadCell} text-right`}>
                    {t("inventory.locations.holds.columns.onHand")}
                  </th>
                  <th scope="col" className={`${listHeadCell} text-right`}>
                    {t("inventory.locations.holds.columns.reserved")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={lot.lot_id} className={listRow}>
                    <th scope="row" className={`${listCell} font-normal`}>
                      <Link
                        to="/parts/$partId"
                        params={{ partId: lot.part_id }}
                        className={`hover:underline ${lot.part_name ? "text-primary" : "text-warn"}`}
                      >
                        {lot.part_name ?? unknown}
                      </Link>
                    </th>
                    <td className={`${listCell} text-right tabular-nums`}>{lot.on_hand}</td>
                    <td className={`${listCell} text-right tabular-nums`}>{lot.reserved}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid gap-2">
        <h2 className="font-display text-lg font-semibold">
          {t("inventory.locations.holds.boards")}
        </h2>
        {boards.isPending && (
          <p className="text-sm text-muted">{t("inventory.locations.holds.loading")}</p>
        )}
        {boards.isError && (
          <p role="alert" className="text-sm text-crit">
            {t("inventory.locations.holds.error")}
          </p>
        )}
        {boards.data && units.length === 0 && (
          <p className="text-sm text-muted">{t("inventory.locations.holds.noBoards")}</p>
        )}
        {units.length > 0 && (
          <div className="overflow-x-auto">
            <table className={listTable}>
              <caption className="sr-only">{t("inventory.locations.holds.boards")}</caption>
              <thead className={listHead}>
                <tr>
                  <th scope="col" className={listHeadCell}>
                    {t("inventory.boards.columns.code")}
                  </th>
                  <th scope="col" className={listHeadCell}>
                    {t("inventory.boards.columns.part")}
                  </th>
                  <th scope="col" className={listHeadCell}>
                    {t("inventory.boards.columns.status")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {units.map((unit) => (
                  <tr key={unit.id} className={listRow}>
                    <th scope="row" className={`${listCell} font-normal`}>
                      <Link
                        to="/units/$unitId"
                        params={{ unitId: unit.id }}
                        className="font-mono text-primary hover:underline"
                      >
                        {unit.code}
                      </Link>
                    </th>
                    <td className={listCell}>{unit.part_name ?? unknown}</td>
                    <td className={listCell}>{t(`inventory.units.status.${unit.status}`)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

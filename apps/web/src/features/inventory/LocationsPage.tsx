import { getRouteApi } from "@tanstack/react-router";
import type { LocationNode } from "@wiredex/api-client";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  locationTree,
  matchesLocation,
  refusalMessage,
  useCreateLocation,
  useDeleteLocation,
  useEditLocation,
  useLocations,
} from "./inventory";
import { LocationTree } from "./LocationTree";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

const route = getRouteApi("/authenticated/locations");

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
  const roots = locationTree(all);
  const shownRoots = locationTree(keptByFilter(all, filter));
  const selected = all.find((location) => location.id === selectedId) ?? null;

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">
        {t("inventory.locations.title")}
      </h1>
      <p className="text-muted">{t("inventory.locations.intro")}</p>

      {locations.isPending && <p className="text-muted">{t("inventory.locations.loading")}</p>}
      {locations.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.locations.error")}
        </p>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="grid gap-4">
          <NewLocationForm parent={selected} />
          {locations.data && roots.length === 0 && (
            <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
              {t("inventory.locations.empty")}
            </p>
          )}
          {roots.length > 0 && (
            <div className="grid gap-1">
              <label htmlFor={filterId} className="text-sm font-medium">
                {t("inventory.locations.filter")}
              </label>
              <input
                id={filterId}
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder={t("inventory.locations.filterPlaceholder")}
                className={control}
              />
            </div>
          )}
          {roots.length > 0 && shownRoots.length === 0 && (
            <p role="status" className="text-muted">
              {t("inventory.locations.filterEmpty")}
            </p>
          )}
          {shownRoots.length > 0 && (
            <LocationTree
              // A new filter draws the tree afresh, so a branch folded earlier can't hide a match.
              key={filter}
              roots={shownRoots}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>
        {selected && (
          <LocationActions
            location={selected}
            locations={all}
            onDeleted={() => setSelectedId(null)}
          />
        )}
        {!selected && roots.length > 0 && (
          <p className="text-muted">{t("inventory.locations.pickOne")}</p>
        )}
      </div>
    </section>
  );
}

/**
 * The locations whose name or short code holds the filter, each with its ancestors, so the
 * tree still shows where a match sits (requirement 9.1). Blank text keeps them all. The list
 * keeps its order, which is the order the tree draws.
 */
function keptByFilter(all: LocationNode[], filter: string): LocationNode[] {
  if (filter.trim() === "") return all;
  const byId = new Map(all.map((location): [string, LocationNode] => [location.id, location]));
  const kept = new Set<string>();
  for (const location of all) {
    if (!matchesLocation(location, filter)) continue;
    let at: LocationNode | undefined = location;
    // Stops at a location already kept: its ancestors are kept too, and a loop ends there.
    while (at && !kept.has(at.id)) {
      kept.add(at.id);
      at = at.parent_id === null ? undefined : byId.get(at.parent_id);
    }
  }
  return all.filter((location) => kept.has(location.id));
}

function NewLocationForm({ parent }: { parent: LocationNode | null }) {
  const { t } = useTranslation();
  const id = useId();
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
    <form onSubmit={submit} className="grid gap-2 rounded-lg border border-border bg-surface p-4">
      <label htmlFor={id} className="text-sm font-medium">
        {t("inventory.locations.add")}
      </label>
      <p className="text-sm text-muted">
        {parent
          ? t("inventory.locations.addUnder", { name: parent.name })
          : t("inventory.locations.addAtRoot")}
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id={id}
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={control}
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("inventory.locations.create")}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-crit">
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

/** Rename, move and delete for the location the tree has selected (requirements 9.1, 9.2). */
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
      <h2 className="font-display text-xl font-semibold">
        {location.name}{" "}
        <span className="font-mono text-base font-normal text-muted">{location.code}</span>
      </h2>

      <form onSubmit={rename} className="grid gap-2">
        <label htmlFor={nameId} className="text-sm font-medium">
          {t("inventory.locations.renameLabel")}
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id={nameId}
            name="name"
            type="text"
            defaultValue={location.name}
            // Remounts with the location, so the box always holds the selected name.
            key={location.id}
            className={control}
          />
          <button type="submit" className={action} disabled={edit.isPending}>
            {t("inventory.locations.rename")}
          </button>
        </div>
      </form>

      <div className="grid gap-2">
        <label htmlFor={parentId} className="text-sm font-medium">
          {t("inventory.locations.moveLabel")}
        </label>
        <select
          id={parentId}
          value={location.parent_id ?? ""}
          onChange={(event) => move(event.target.value)}
          className={control}
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

      {edit.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(edit.error) ?? t("inventory.locations.editError")}
        </p>
      )}

      {!asking && (
        <button
          type="button"
          onClick={() => setAsking(true)}
          className="justify-self-start rounded-md border border-crit px-3 py-1.5 text-sm text-crit hover:bg-surface-2"
        >
          {t("inventory.locations.delete")}
        </button>
      )}
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
              className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {t("inventory.locations.deleteConfirm")}
            </button>
            <button type="button" onClick={() => setAsking(false)} className={action}>
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
    </section>
  );
}

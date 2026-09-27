import type { LocationNode } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  locationTree,
  refusalMessage,
  useCreateLocation,
  useDeleteLocation,
  useEditLocation,
  useLocations,
} from "./inventory";
import { LocationTree } from "./LocationTree";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

export function LocationsPage() {
  const { t } = useTranslation();
  const locations = useLocations();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const all = locations.data ?? [];
  const roots = locationTree(all);
  const selected = all.find((location) => location.id === selectedId) ?? null;

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
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
            <LocationTree roots={roots} selectedId={selectedId} onSelect={setSelectedId} />
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

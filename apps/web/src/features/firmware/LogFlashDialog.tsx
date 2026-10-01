import { useQuery } from "@tanstack/react-query";
import type { FirmwareField, FirmwareSummary, UnitResponse } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { isHeld } from "../inventory/inventory";
import { control, dialogPrimary, StockDialog } from "../inventory/StockDialog";
import { FirmwareRefusal, firmwareQuery, revisionFirmwareQuery, useFirmwareList } from "./firmware";
import { FUTURE_ALLOWANCE_MS, localInputValue, useLogFlash, withOffset } from "./flashes";
import { refusalKey } from "./labels";

const MAX_NOTES_LENGTH = 500;

/** The fields the dialog shows a refusal on; the rest, `unit_retired` among them, are its own. */
type DialogField = Extract<FirmwareField, "version" | "flashed_at" | "notes">;
type Problems = Partial<Record<DialogField, string>>;

type Props = { unit: UnitResponse; onClose: () => void };

/**
 * Logs a flash on a unit (requirement 8.2): *Firmware*, those running on the revision holding
 * the unit in their own group first, then the rest by name; *Version*, the chosen firmware's
 * released versions highest first, since a draft can still change (decision 2); *Flashed at*,
 * now unless changed; and *Notes*. A time left as it opened is sent as none, so the API dates
 * the flash by its own clock rather than a phone's (requirement 1.2); a changed one goes with
 * the browser's offset, and one more than five minutes ahead is marked before anything is sent.
 */
export function LogFlashDialog({ unit, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const log = useLogFlash();
  const firmwareId = useId();
  const versionId = useId();
  const timeId = useId();
  const notesId = useId();

  const holding = isHeld(unit.status) ? unit.revision_id : null;
  const workspace = useFirmwareList("");
  const onRevision = useQuery({
    ...revisionFirmwareQuery(holding ?? ""),
    enabled: holding !== null,
  });
  // A revision gone from the workspace runs nothing here: its firmware is listed with the rest.
  const running = holding ? (onRevision.data ?? []) : [];
  const runningIds = new Set(running.map((firmware) => firmware.id));
  const others = (workspace.data ?? [])
    .filter((firmware) => !runningIds.has(firmware.id))
    .sort((a, b) => a.name.localeCompare(b.name, i18n.language));
  const offered = [...running, ...others];
  const loading = workspace.isPending || (holding !== null && onRevision.isPending);

  const [chosenFirmware, setChosenFirmware] = useState("");
  const firmware = offered.find((item) => item.id === chosenFirmware) ?? offered[0];
  const details = useQuery({ ...firmwareQuery(firmware?.id ?? ""), enabled: Boolean(firmware) });
  const released = (details.data?.versions ?? []).filter((item) => item.status === "released");
  const [chosenVersion, setChosenVersion] = useState("");
  const version = released.find((item) => item.id === chosenVersion) ?? released[0];

  const [opened] = useState(() => localInputValue(new Date()));
  const [flashedAt, setFlashedAt] = useState(opened);
  const [notes, setNotes] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  const refused = refusalOf(t, log.error);
  const versionProblem = problems.version ?? refused.fields.version;
  const timeProblem = problems.flashed_at ?? refused.fields.flashed_at;
  const notesProblem = problems.notes ?? refused.fields.notes;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!version) return;
    const found: Problems = {};
    const untouched = flashedAt === opened || flashedAt.trim() === "";
    const sentAt = untouched ? null : withOffset(flashedAt);
    if (!untouched && sentAt === null) {
      found.flashed_at = t("firmware.flash.dialog.error.time");
    } else if (sentAt !== null && Date.parse(sentAt) > Date.now() + FUTURE_ALLOWANCE_MS) {
      found.flashed_at = t("firmware.refusal.flashed_in_future");
    }
    // Trimmed and collapsed as the API keeps them; blank notes are none (requirement 1.9).
    const text = notes.trim().replace(/\s+/g, " ");
    if ([...text].length > MAX_NOTES_LENGTH) {
      found.notes = t("firmware.flash.dialog.error.notesTooLong", { max: MAX_NOTES_LENGTH });
    }
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    log.mutate(
      {
        unitId: unit.id,
        body: { version_id: version.id, flashed_at: sentAt, notes: text || null },
      },
      { onSuccess: onClose },
    );
  }

  const option = (item: FirmwareSummary) => (
    <option key={item.id} value={item.id}>
      {item.name}
    </option>
  );

  return (
    <StockDialog title={t("firmware.flash.dialog.title", { code: unit.code })} onClose={onClose}>
      {loading ? (
        <p className="text-muted">{t("firmware.flash.dialog.loading")}</p>
      ) : !firmware ? (
        <>
          <p className={workspace.isError ? "text-crit" : "text-muted"}>
            {workspace.isError
              ? t("firmware.flash.dialog.loadError")
              : t("firmware.flash.dialog.noFirmware")}
          </p>
          <button type="button" onClick={onClose} className={`${control} justify-self-start`}>
            {t("firmware.flash.dialog.cancel")}
          </button>
        </>
      ) : (
        <form noValidate onSubmit={submit} className="grid gap-3">
          <div className="grid gap-1">
            <label htmlFor={firmwareId} className="text-sm font-medium">
              {t("firmware.flash.dialog.firmware")}
            </label>
            <select
              id={firmwareId}
              value={firmware.id}
              onChange={(event) => {
                setChosenFirmware(event.target.value);
                setChosenVersion("");
              }}
              className={control}
            >
              {running.length > 0 ? (
                <>
                  <optgroup label={t("firmware.flash.dialog.onRevision")}>
                    {running.map(option)}
                  </optgroup>
                  {others.length > 0 && (
                    <optgroup label={t("firmware.flash.dialog.otherFirmware")}>
                      {others.map(option)}
                    </optgroup>
                  )}
                </>
              ) : (
                others.map(option)
              )}
            </select>
          </div>

          <div className="grid gap-1">
            {details.isPending ? (
              <p className="text-sm text-muted">{t("firmware.flash.dialog.loadingVersions")}</p>
            ) : details.isError ? (
              <p role="alert" className="text-sm text-crit">
                {t("firmware.flash.dialog.versionsError")}
              </p>
            ) : version ? (
              <>
                <label htmlFor={versionId} className="text-sm font-medium">
                  {t("firmware.flash.dialog.version")}
                </label>
                <select
                  id={versionId}
                  value={version.id}
                  onChange={(event) => setChosenVersion(event.target.value)}
                  className={`${control} font-mono`}
                  aria-invalid={versionProblem ? true : undefined}
                  aria-describedby={versionProblem ? `${versionId}-error` : undefined}
                >
                  {released.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.version}
                    </option>
                  ))}
                </select>
              </>
            ) : (
              <p className="text-sm text-muted">
                {t("firmware.flash.dialog.noRelease", { name: firmware.name })}
              </p>
            )}
            {versionProblem && (
              <p id={`${versionId}-error`} className="text-sm text-crit">
                {versionProblem}
              </p>
            )}
          </div>

          <div className="grid gap-1">
            <label htmlFor={timeId} className="text-sm font-medium">
              {t("firmware.flash.dialog.flashedAt")}
            </label>
            <input
              id={timeId}
              type="datetime-local"
              value={flashedAt}
              max={localInputValue(new Date(Date.now() + FUTURE_ALLOWANCE_MS))}
              onChange={(event) => setFlashedAt(event.target.value)}
              className={control}
              aria-invalid={timeProblem ? true : undefined}
              aria-describedby={`${timeId}-hint${timeProblem ? ` ${timeId}-error` : ""}`}
            />
            <p id={`${timeId}-hint`} className="text-sm text-muted">
              {t("firmware.flash.dialog.flashedAtHint")}
            </p>
            {timeProblem && (
              <p id={`${timeId}-error`} className="text-sm text-crit">
                {timeProblem}
              </p>
            )}
          </div>

          <div className="grid gap-1">
            <label htmlFor={notesId} className="text-sm font-medium">
              {t("firmware.flash.dialog.notes")}
            </label>
            <input
              id={notesId}
              type="text"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className={control}
              aria-invalid={notesProblem ? true : undefined}
              aria-describedby={`${notesId}-hint${notesProblem ? ` ${notesId}-error` : ""}`}
            />
            <p id={`${notesId}-hint`} className="text-sm text-muted">
              {t("firmware.flash.dialog.notesHint", { max: MAX_NOTES_LENGTH })}
            </p>
            {notesProblem && (
              <p id={`${notesId}-error`} className="text-sm text-crit">
                {notesProblem}
              </p>
            )}
          </div>

          {refused.form && (
            <p role="alert" className="text-sm text-crit">
              {refused.form}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={!version || log.isPending} className={dialogPrimary}>
              {t("firmware.flash.dialog.submit")}
            </button>
            <button type="button" onClick={onClose} className={control}>
              {t("firmware.flash.dialog.cancel")}
            </button>
          </div>
        </form>
      )}
    </StockDialog>
  );
}

/**
 * A refused flash, as the sentences the dialog shows: on the field it names, from its code; a
 * 404 says the board or the version is gone; the rest, a retired unit among them, is the
 * dialog's own, the API's sentence when no code of ours fits.
 */
function refusalOf(t: TFunction, error: unknown): { fields: Problems; form: string | null } {
  if (!error) return { fields: {}, form: null };
  const refusal = error instanceof FirmwareRefusal ? error : null;
  if (refusal?.status === 404) return { fields: {}, form: t("firmware.flash.dialog.error.gone") };
  const key = refusalKey(refusal?.code ?? null);
  const sentence = key
    ? t(key, { item: refusal?.item ?? "" })
    : t("firmware.flash.dialog.error.save");
  const field = refusal?.field;
  if (field === "version" || field === "flashed_at" || field === "notes") {
    return { fields: { [field]: sentence }, form: null };
  }
  return { fields: {}, form: sentence };
}

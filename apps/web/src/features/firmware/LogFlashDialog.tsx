import { useQuery } from "@tanstack/react-query";
import type {
  FirmwareDetails,
  FirmwareSummary,
  FirmwareVersion,
  UnitResponse,
} from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { isHeld } from "../inventory/inventory";
import { control, dialogPrimary, StockDialog } from "../inventory/StockDialog";
import { type PickedUnit, UnitPicker } from "../inventory/UnitPicker";
import { firmwareQuery, revisionFirmwareQuery, useFirmwareList } from "./firmware";
import { FUTURE_ALLOWANCE_MS, localInputValue, useLogFlash, withOffset } from "./flashes";
import {
  cleanNotes,
  type FormProps,
  MAX_NOTES_LENGTH,
  NotesField,
  type Problems,
  refusalOf,
} from "./flashForm";
import { WriteFlashForm } from "./flashing/WriteFlashForm";

type Props = ({ unit: UnitResponse } | { firmware: FirmwareDetails; version: FirmwareVersion }) & {
  /** Write the version onto the board over a serial port first, then log it. */
  write?: boolean;
  onClose: () => void;
};

/**
 * Logs a flash from either end (decision 14): fixed on a unit, from its page, or fixed on a
 * released version, from its panel. Each end chooses the other, and both then take the same
 * *Flashed at* and *Notes*, checked and refused alike. With `write` the same choice is made,
 * then the browser writes the board itself and logs the flash once it is verified.
 */
export function LogFlashDialog({ write = false, onClose, ...end }: Props) {
  // A write isn't left half done: the dialog stays until the board is whole again.
  const [busy, setBusy] = useState(false);
  const shared = { write, onClose: busy ? stay : onClose, onBusy: setBusy };
  return "unit" in end ? (
    <OnUnit unit={end.unit} {...shared} />
  ) : (
    <OnVersion firmware={end.firmware} version={end.version} {...shared} />
  );
}

function stay() {}

type EndProps = { write: boolean; onClose: () => void; onBusy: (busy: boolean) => void };

/**
 * Fixed on a unit (requirement 8.2): *Firmware*, those running on the revision holding the unit
 * in their own group first, then the rest by name; *Version*, the chosen firmware's released
 * versions highest first, since a draft can still change (decision 2).
 */
function OnUnit({ unit, write, onClose, onBusy }: EndProps & { unit: UnitResponse }) {
  const { t, i18n } = useTranslation();
  const Form = write ? WriteFlashForm : FlashForm;
  const firmwareId = useId();
  const versionId = useId();

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

  const option = (item: FirmwareSummary) => (
    <option key={item.id} value={item.id}>
      {item.name}
    </option>
  );

  return (
    <StockDialog
      title={t(write ? "firmware.flash.write.title" : "firmware.flash.dialog.title", {
        code: unit.code,
      })}
      onClose={onClose}
      wide={write}
    >
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
        // A firmware with no release leaves nothing to log, which the line under it says.
        <Form
          choice="version"
          target={version ? { unitId: unit.id, versionId: version.id } : null}
          board={firmware.target}
          onClose={onClose}
          onBusy={onBusy}
        >
          {(versionProblem) => (
            <>
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
            </>
          )}
        </Form>
      )}
    </StockDialog>
  );
}

type OnVersionProps = EndProps & { firmware: FirmwareDetails; version: FirmwareVersion };

/**
 * Fixed on a released version, from its panel (requirement 8.3): *Board*, found by its code,
 * serial or MAC, a retired one listed but unavailable, since it can't be flashed (1.6).
 */
function OnVersion({ firmware, version, write, onClose, onBusy }: OnVersionProps) {
  const { t } = useTranslation();
  const Form = write ? WriteFlashForm : FlashForm;
  const boardId = useId();
  const [board, setBoard] = useState<PickedUnit | null>(null);

  return (
    <StockDialog
      title={t(
        write ? "firmware.flash.write.titleOfVersion" : "firmware.flash.dialog.titleOfVersion",
        { name: firmware.name, version: version.version },
      )}
      onClose={onClose}
      wide={write}
    >
      <Form
        choice="unit"
        target={board ? { unitId: board.id, versionId: version.id } : null}
        unchosen={t(
          write ? "firmware.flash.write.error.board" : "firmware.flash.dialog.error.board",
        )}
        board={firmware.target}
        onClose={onClose}
        onBusy={onBusy}
      >
        {(boardProblem) => (
          <div className="grid gap-1">
            <UnitPicker
              label={t("firmware.flash.dialog.board")}
              value={board}
              onChange={setBoard}
              invalid={Boolean(boardProblem)}
              describedBy={boardProblem ? `${boardId}-error` : undefined}
            />
            {boardProblem && (
              <p id={`${boardId}-error`} className="text-sm text-crit">
                {boardProblem}
              </p>
            )}
          </div>
        )}
      </Form>
    </StockDialog>
  );
}

/**
 * The form both ends share: their choice, then *Flashed at*, now unless changed, and *Notes*.
 * A time left as it opened is sent as none, so the API dates the flash by its own clock rather
 * than a phone's (requirement 1.2); a changed one goes with the browser's offset, and one more
 * than five minutes ahead is marked before anything is sent.
 */
function FlashForm({ target, choice, unchosen, onClose, children }: FormProps) {
  const { t } = useTranslation();
  const log = useLogFlash();
  const timeId = useId();

  const [opened] = useState(() => localInputValue(new Date()));
  const [flashedAt, setFlashedAt] = useState(opened);
  const [notes, setNotes] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  const refused = refusalOf(t, log.error, choice);
  // Asking for the choice stops once it is made.
  const choiceProblem = (target ? undefined : problems[choice]) ?? refused.fields[choice];
  const timeProblem = problems.flashed_at ?? refused.fields.flashed_at;
  const notesProblem = problems.notes ?? refused.fields.notes;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Problems = {};
    if (!target) {
      if (!unchosen) return;
      found[choice] = unchosen;
    }
    const untouched = flashedAt === opened || flashedAt.trim() === "";
    const sentAt = untouched ? null : withOffset(flashedAt);
    if (!untouched && sentAt === null) {
      found.flashed_at = t("firmware.flash.dialog.error.time");
    } else if (sentAt !== null && Date.parse(sentAt) > Date.now() + FUTURE_ALLOWANCE_MS) {
      found.flashed_at = t("firmware.refusal.flashed_in_future");
    }
    const text = cleanNotes(notes);
    if ([...text].length > MAX_NOTES_LENGTH) {
      found.notes = t("firmware.flash.dialog.error.notesTooLong", { max: MAX_NOTES_LENGTH });
    }
    setProblems(found);
    if (!target || Object.keys(found).length > 0) return;
    log.mutate(
      {
        unitId: target.unitId,
        body: { version_id: target.versionId, flashed_at: sentAt, notes: text || null },
      },
      { onSuccess: onClose },
    );
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-3">
      {children(choiceProblem)}

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

      <NotesField value={notes} onChange={setNotes} problem={notesProblem} />

      {refused.form && (
        <p role="alert" className="text-sm text-crit">
          {refused.form}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={(!target && !unchosen) || log.isPending}
          className={dialogPrimary}
        >
          {t("firmware.flash.dialog.submit")}
        </button>
        <button type="button" onClick={onClose} className={control}>
          {t("firmware.flash.dialog.cancel")}
        </button>
      </div>
    </form>
  );
}

import {
  type ChangeEvent,
  type FormEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../../files/sizes";
import { control, dialogPrimary } from "../../inventory/StockDialog";
import { useLogFlash } from "../flashes";
import {
  cleanNotes,
  type FormProps,
  refusalOf as logRefusalOf,
  MAX_NOTES_LENGTH,
  NotesField,
  type Problems,
} from "../flashForm";
import { type Chip, choosePort, connect, type Flasher, serialSupported } from "./flasher";
import {
  type FlashImage,
  hex,
  type ImageProblem,
  type PlacedImage,
  placed,
  problemsOf,
  refusalOf,
  suggestedOffset,
} from "./images";
import { type StoredBuild, useStoredBuild } from "./useStoredBuild";

/** The loader's lines kept for *Loader output*: the end of a long write, not all of it. */
const KEPT_LINES = 200;

/**
 * Where a flash is: waiting for *Connect and flash*; in the chip's loader; writing; logging
 * what was written; written but not logged, which is asked again; or done.
 */
type Phase = "idle" | "connecting" | "writing" | "logging" | "unlogged" | "done";

type Target = NonNullable<FormProps["target"]>;

/**
 * Writes a released version onto a board over a serial port, then logs the flash (ADR 0006's
 * amendment). The binaries are the version's stored build when it has one (spec 20), so nothing
 * is chosen, or files from this computer, which never leave it. Either way they pass the same
 * checks, nothing is logged unless every binary read back from the flash as it was sent, and
 * the log's time is the API's clock.
 */
export function WriteFlashForm({
  target,
  versionId,
  choice,
  unchosen,
  board,
  onClose,
  onBusy,
  children,
}: FormProps) {
  const { t, i18n } = useTranslation();
  const log = useLogFlash();
  const filesId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(0);
  // The loader holding the port, freed if the dialog goes while it does.
  const held = useRef<Flasher | null>(null);

  const [images, setImages] = useState<FlashImage[]>([]);
  const stored = useStoredBuild(versionId);
  // The version's build unless the owner asks for files, or there is none to use.
  const [fromComputer, setFromComputer] = useState(false);
  const storedImages = useMemo<FlashImage[]>(
    () =>
      stored.state === "ready"
        ? stored.bundle.images.map((image, index) => ({ ...image, id: `stored-${index}` }))
        : [],
    [stored],
  );
  const usingStored = stored.state === "ready" && !fromComputer;
  const chosen = usingStored ? storedImages : images;
  const [eraseAll, setEraseAll] = useState(false);
  const [notes, setNotes] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  // Problems show once *Connect and flash* is asked, not while the offsets are being typed.
  const [asked, setAsked] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [failure, setFailure] = useState<string | null>(null);
  const [writing, setWriting] = useState<{ name: string; fraction: number } | null>(null);
  const [chip, setChip] = useState<Chip | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [written, setWritten] = useState<{ target: Target; notes: string } | null>(null);

  const busy = phase === "connecting" || phase === "writing";
  // A stored build's problems show at once: there is nothing to type that would fix them.
  const imageProblems = asked || usingStored ? problemsOf(chosen) : new Map<string, ImageProblem>();
  const refused = logRefusalOf(t, log.error, choice);
  const choiceProblem = target ? undefined : problems[choice];

  useEffect(() => {
    onBusy(busy);
    if (!busy) return;
    // Leaving the page mid-write would cut it too.
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy, onBusy]);

  useEffect(
    () => () => {
      void held.current?.release();
    },
    [],
  );

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const chosen = [...(event.target.files ?? [])];
    const read = await Promise.all(
      chosen.map(async (file) => ({
        id: String(nextId.current++),
        name: file.name,
        bytes: new Uint8Array(await file.arrayBuffer()),
        offset: suggestedOffset(file.name, board),
      })),
    );
    setImages((current) => [...current, ...read]);
    // Emptied, so a file removed from the list can be chosen again.
    if (inputRef.current) inputRef.current.value = "";
  }

  function problemText(problem: ImageProblem | undefined): string | undefined {
    if (!problem) return undefined;
    return problem.kind === "overlap"
      ? t("firmware.flash.write.error.overlap", { other: problem.other })
      : t(`firmware.flash.write.error.${problem.kind}`);
  }

  async function flash(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Problems = {};
    if (!target) {
      if (!unchosen) return;
      found[choice] = unchosen;
    }
    const text = cleanNotes(notes);
    if ([...text].length > MAX_NOTES_LENGTH) {
      found.notes = t("firmware.flash.dialog.error.notesTooLong", { max: MAX_NOTES_LENGTH });
    }
    setProblems(found);
    setAsked(true);
    const ready = placed(chosen);
    if (!target || !ready || ready.length === 0 || Object.keys(found).length > 0) return;

    setFailure(null);
    setLines([]);
    setChip(null);
    let port: SerialPort | null;
    try {
      // First, while the click still counts: the browser shows its chooser for nothing else.
      port = await choosePort();
    } catch {
      setFailure(t("firmware.flash.write.error.port"));
      return;
    }
    if (!port) return;

    setPhase("connecting");
    let flasher: Flasher;
    try {
      flasher = await connect(port, (line) =>
        setLines((current) => [...current, line].slice(-KEPT_LINES)),
      );
    } catch {
      setPhase("idle");
      setFailure(t("firmware.flash.write.error.connect"));
      return;
    }
    held.current = flasher;
    setChip(flasher.chip);

    const refusal = layoutRefusal(ready, flasher.chip);
    if (refusal) {
      await flasher.release();
      held.current = null;
      setPhase("idle");
      setFailure(refusal);
      return;
    }

    setPhase("writing");
    const total = ready.reduce((sum, image) => sum + image.bytes.length, 0);
    try {
      await flasher.write(ready, {
        eraseAll,
        onProgress: (progress) => {
          const before = ready
            .slice(0, progress.file)
            .reduce((sum, image) => sum + image.bytes.length, 0);
          const image = ready[progress.file];
          const share = progress.total > 0 ? progress.written / progress.total : 1;
          setWriting({
            name: image?.name ?? "",
            fraction: (before + share * (image?.bytes.length ?? 0)) / total,
          });
        },
      });
    } catch (error) {
      await flasher.release();
      held.current = null;
      setPhase("idle");
      setWriting(null);
      setFailure(t("firmware.flash.write.error.write", { reason: reasonOf(error) }));
      return;
    }
    // Written and verified: a reset that fails leaves a board that starts at its next power-up.
    await flasher.restart().catch(() => {});
    held.current = null;
    setWritten({ target, notes: text });
    await record({ target, notes: text });
  }

  function layoutRefusal(ready: PlacedImage[], connected: Chip): string | null {
    const refusal = refusalOf(ready, connected);
    if (!refusal) return null;
    return refusal.kind === "bootloader"
      ? t("firmware.flash.write.error.bootloader", {
          chip: connected.name,
          name: refusal.name,
          offset: hex(refusal.address),
          expected: hex(refusal.expected),
        })
      : t("firmware.flash.write.error.fit", {
          name: refusal.name,
          size: formatSize(refusal.flashBytes, i18n.language),
        });
  }

  /** Logs what was written, as now: asked again from *Log it again* when it is refused. */
  async function record(flashed: { target: Target; notes: string }) {
    setPhase("logging");
    try {
      await log.mutateAsync({
        unitId: flashed.target.unitId,
        body: {
          version_id: flashed.target.versionId,
          flashed_at: null,
          notes: flashed.notes || null,
        },
      });
      setPhase("done");
    } catch {
      setPhase("unlogged");
    }
  }

  if (!serialSupported()) {
    return (
      <>
        <p className="text-muted">{t("firmware.flash.write.unsupported")}</p>
        <button type="button" onClick={onClose} className={`${control} justify-self-start`}>
          {t("firmware.flash.dialog.cancel")}
        </button>
      </>
    );
  }

  if (phase === "logging" || phase === "unlogged" || phase === "done") {
    return (
      <div className="grid gap-3">
        <p role="status">
          {t(phase === "done" ? "firmware.flash.write.done" : "firmware.flash.write.written", {
            chip: chip?.name ?? "",
          })}
        </p>
        {chip?.mac && (
          <p className="text-sm text-muted">
            {t("firmware.flash.write.mac")} <span className="font-mono">{chip.mac}</span>
          </p>
        )}
        {phase === "unlogged" && (
          <p role="alert" className="text-sm text-crit">
            {t("firmware.flash.write.error.unlogged", {
              reason: refused.form ?? Object.values(refused.fields)[0] ?? "",
            })}
          </p>
        )}
        <LoaderOutput lines={lines} />
        <div className="flex flex-wrap gap-2">
          {phase !== "done" && (
            <button
              type="button"
              disabled={phase === "logging" || !written}
              onClick={() => written && void record(written)}
              className={dialogPrimary}
            >
              {t("firmware.flash.write.logAgain")}
            </button>
          )}
          <button type="button" onClick={onClose} className={control}>
            {t("firmware.flash.write.close")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={(event) => void flash(event)} className="grid gap-3">
      {/* Off while the board is being written, so what is logged is what was chosen. */}
      <fieldset disabled={busy} className="grid min-w-0 gap-3">
        {children(choiceProblem)}

        {stored.state === "loading" ? (
          <p className="text-sm text-muted">{t("firmware.flash.write.stored.loading")}</p>
        ) : usingStored ? (
          <StoredBinaries
            build={stored}
            board={board}
            images={storedImages}
            problemOf={(image) => problemText(imageProblems.get(image.id))}
            onUseComputer={() => setFromComputer(true)}
          />
        ) : (
          <>
            <div className="grid min-w-0 gap-1">
              <label htmlFor={filesId} className="text-sm font-medium">
                {t("firmware.flash.write.files")}
              </label>
              <input
                ref={inputRef}
                id={filesId}
                type="file"
                multiple
                accept=".bin"
                onChange={(event) => void choose(event)}
                aria-describedby={`${filesId}-hint`}
                // The input is emptied after each choice, so its own "No file chosen" would sit
                // beside a list of chosen files: the list below is what says what is chosen.
                className="min-w-0 text-sm text-transparent file:mr-3 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-text"
              />
              <p id={`${filesId}-hint`} className="text-sm text-muted">
                {t("firmware.flash.write.filesHint")}
              </p>
              <StoredNote build={stored} onUseStored={() => setFromComputer(false)} />
              {asked && images.length === 0 && (
                <p role="alert" className="text-sm text-crit">
                  {t("firmware.flash.write.error.noFiles")}
                </p>
              )}
            </div>

            {images.length > 0 && (
              <>
                <ul className="grid gap-2">
                  {images.map((image) => (
                    <ImageRow
                      key={image.id}
                      image={image}
                      problem={problemText(imageProblems.get(image.id))}
                      onOffset={(offset) =>
                        setImages((current) =>
                          current.map((item) =>
                            item.id === image.id ? { ...item, offset } : item,
                          ),
                        )
                      }
                      onRemove={() =>
                        setImages((current) => current.filter((item) => item.id !== image.id))
                      }
                    />
                  ))}
                </ul>
                <p className="text-sm text-muted">{t("firmware.flash.write.offsetHint")}</p>
              </>
            )}
          </>
        )}

        <div className="grid gap-1">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={eraseAll}
              onChange={(event) => setEraseAll(event.target.checked)}
              className="size-4 accent-primary"
            />
            {t("firmware.flash.write.eraseAll")}
          </label>
          <p className="text-sm text-muted">{t("firmware.flash.write.eraseAllHint")}</p>
        </div>

        <NotesField value={notes} onChange={setNotes} problem={problems.notes} />
      </fieldset>

      <p role="status" className="text-sm">
        {phase === "connecting" && t("firmware.flash.write.connecting")}
        {phase === "writing" &&
          (writing
            ? t("firmware.flash.write.writing", { name: writing.name })
            : t("firmware.flash.write.erasing", { chip: chip?.name ?? "" }))}
      </p>
      {phase === "writing" && (
        <progress
          aria-label={t("firmware.flash.write.progress")}
          max={1}
          value={writing?.fraction ?? 0}
          className="h-2 w-full accent-primary"
        />
      )}
      {failure && (
        <p role="alert" className="text-sm text-crit">
          {failure}
        </p>
      )}
      <LoaderOutput lines={lines} />

      <p className="text-sm text-muted">{t("firmware.flash.write.submitHint")}</p>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={(!target && !unchosen) || busy} className={dialogPrimary}>
          {t("firmware.flash.write.submit")}
        </button>
        <button type="button" disabled={busy} onClick={onClose} className={control}>
          {t("firmware.flash.dialog.cancel")}
        </button>
      </div>
    </form>
  );
}

type StoredProps = {
  build: Extract<StoredBuild, { state: "ready" }>;
  /** The firmware's board now, which the build's is checked against. */
  board: string;
  images: FlashImage[];
  problemOf: (image: FlashImage) => string | undefined;
  onUseComputer: () => void;
};

/**
 * The version's stored build, in place of the file picker (spec 20, requirement 3.1): what it
 * is called, its binaries and the offsets its manifest gives them, which aren't typed over,
 * and a way to choose files from the computer instead.
 */
function StoredBinaries({ build, board, images, problemOf, onUseComputer }: StoredProps) {
  const { t, i18n } = useTranslation();
  const built = build.bundle.board;
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-sm font-medium">{t("firmware.flash.write.stored.title")}</p>
      <p className="text-sm break-words">{build.attachment.title}</p>
      {built !== "" && built !== board && (
        <p className="text-sm font-semibold text-warn">
          <span aria-hidden="true">⚠ </span>
          {t("firmware.flash.write.stored.boardChanged", { built, board })}
        </p>
      )}
      <ul aria-label={t("firmware.flash.write.files")} className="grid gap-1">
        {images.map((image) => {
          const problem = problemOf(image);
          return (
            <li key={image.id} className="grid gap-1 rounded-md border border-border px-2 py-1">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="min-w-0 flex-1 break-all font-mono text-sm">{image.name}</span>
                <span className="text-sm text-muted">
                  {formatSize(image.bytes.length, i18n.language)}
                </span>
                <span className="font-mono text-sm">
                  {t("firmware.flash.write.stored.offset", { offset: image.offset })}
                </span>
              </div>
              {problem && <p className="text-sm text-crit">{problem}</p>}
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        onClick={onUseComputer}
        className={`${control} justify-self-start text-sm`}
      >
        {t("firmware.flash.write.stored.useComputer")}
      </button>
    </div>
  );
}

/**
 * Under the file picker, what there is to know about the version's build: none stored, one
 * that can't be written from here and why, or one set aside that can be taken back.
 */
function StoredNote({ build, onUseStored }: { build: StoredBuild; onUseStored: () => void }) {
  const { t } = useTranslation();
  if (build.state === "none") {
    return <p className="text-sm text-muted">{t("firmware.flash.write.stored.none")}</p>;
  }
  if (build.state === "ready") {
    return (
      <button
        type="button"
        onClick={onUseStored}
        className={`${control} justify-self-start text-sm`}
      >
        {t("firmware.flash.write.stored.useStored")}
      </button>
    );
  }
  if (build.state !== "unreadable") return null;
  const kind = build.problem?.kind ?? "fetch";
  return (
    <p role="alert" className="text-sm text-crit">
      {t("firmware.flash.write.stored.unreadable.intro", { title: build.attachment.title })}{" "}
      {t(`firmware.flash.write.stored.unreadable.${kind}`, { file: build.problem?.file ?? "" })}
    </p>
  );
}

type RowProps = {
  image: FlashImage;
  problem: string | undefined;
  onOffset: (offset: string) => void;
  onRemove: () => void;
};

/** One binary: its name and size, the offset it is written at, and *Remove*. */
function ImageRow({ image, problem, onOffset, onRemove }: RowProps) {
  const { t, i18n } = useTranslation();
  const offsetId = useId();
  return (
    <li className="grid gap-1 rounded-md border border-border p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 break-all font-mono text-sm">{image.name}</span>
        <span className="text-sm text-muted">{formatSize(image.bytes.length, i18n.language)}</span>
        <input
          id={offsetId}
          type="text"
          value={image.offset}
          onChange={(event) => onOffset(event.target.value)}
          aria-label={t("firmware.flash.write.offsetOf", { name: image.name })}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${offsetId}-error` : undefined}
          spellCheck={false}
          className={`${control} w-28 py-1 font-mono text-sm`}
        />
        <button
          type="button"
          onClick={onRemove}
          aria-label={t("firmware.flash.write.removeFile", { name: image.name })}
          className="rounded-md border border-border-strong px-2 py-1 text-sm hover:bg-surface-2"
        >
          {t("firmware.flash.remove")}
        </button>
      </div>
      {problem && (
        <p id={`${offsetId}-error`} className="text-sm text-crit">
          {problem}
        </p>
      )}
    </li>
  );
}

/** What the loader printed, as esptool would in a terminal, for when a flash goes wrong. */
function LoaderOutput({ lines }: { lines: string[] }) {
  const { t } = useTranslation();
  if (lines.length === 0) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted">{t("firmware.flash.write.output")}</summary>
      <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-xs whitespace-pre-wrap">
        {lines.join("\n")}
      </pre>
    </details>
  );
}

function reasonOf(error: unknown): string {
  return error instanceof Error && error.message ? error.message : String(error);
}

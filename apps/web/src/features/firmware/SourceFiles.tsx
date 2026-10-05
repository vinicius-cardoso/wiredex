import type { FirmwareVersion, Framework, SourceFile } from "@wiredex/api-client";
import {
  lazy,
  type ReactNode,
  type RefObject,
  Suspense,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../files/sizes";
import { AddFilesFromDisk } from "./AddFilesFromDisk";
import { FirmwareRefusal, useRemoveSourceFile } from "./firmware";
import { refusalKey } from "./labels";
import { SourceFileEditor } from "./SourceFileEditor";
import { CopyButton } from "./source/CopyButton";
import { HIGHLIGHT_LIMITS, highlightable } from "./source/languages";
import { PlainSource } from "./source/PlainSource";
import { SourceErrorBoundary } from "./source/SourceErrorBoundary";
import { useWrap } from "./source/useWrap";

// The highlighter and its grammars load with the first file shown, not with the app, so a page
// with no source never fetches them (decision 5, requirement 7.4).
const SourceView = lazy(() =>
  import("./source/SourceView").then((module) => ({ default: module.SourceView })),
);

type Props = { version: FirmwareVersion; framework: Framework };

const action = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

/**
 * A version's source files in the API's order, `.ino` first (requirement 7.10), as a folder
 * reads: a list of links, each with its size and line count, and beside it the one file that was
 * picked, a region named by its path with *Copy* and its text exactly as stored, highlighted and
 * numbered by 14's viewer. No file's text is on the page until it is picked. A draft also shows
 * what it holds against its limits, adds files typed or chosen on the computer, and edits and
 * removes the open file in place (requirement 11.9).
 */
export function SourceFiles({ version, framework }: Props) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const [wrap, setWrap] = useWrap();
  const files = version.files;
  const draft = version.editable;
  // The open file, by id: a link to `#file-<id>` opens it too, so a file can be linked to.
  const [openId, setOpenId] = useState<string | null>(() => fileInHash());
  useEffect(() => {
    const follow = () => setOpenId(fileInHash());
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const open = files.find((file) => file.id === openId) ?? null;

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 id={headingId} className="text-sm font-semibold">
          {t("firmware.files.title")}
        </h3>
        {draft ? (
          <p className="text-sm text-muted">
            {t("firmware.files.limits", {
              size: formatSize(version.size, i18n.language),
              limit: formatSize(version.size_limit, i18n.language),
              files: files.length,
              max: version.file_limit,
            })}
          </p>
        ) : (
          files.length > 0 && (
            <p className="text-sm text-muted">
              {t("firmware.files.summary", {
                count: files.length,
                size: formatSize(version.size, i18n.language),
              })}
            </p>
          )
        )}
      </div>

      {files.length === 0 && <p className="text-sm text-muted">{t("firmware.files.empty")}</p>}

      {draft && <AddFiles version={version} framework={framework} />}
      {files.length > 0 && (
        // The files as a list, and the one that was picked beside it: a version reads like a
        // folder, and no file's text is on the page until it is asked for.
        <div className="grid min-w-0 items-start gap-3 xl:grid-cols-[minmax(16rem,24rem)_minmax(0,1fr)]">
          <nav
            aria-label={t("firmware.files.index")}
            className="min-w-0 overflow-hidden rounded-lg border border-border"
          >
            <ul>
              {files.map((file) => {
                const current = file.id === open?.id;
                return (
                  <li key={file.id} className="border-b border-border last:border-b-0">
                    <a
                      href={`#${anchorOf(file)}`}
                      aria-current={current ? "true" : undefined}
                      onClick={() => setOpenId(file.id)}
                      className={`flex items-baseline justify-between gap-3 px-3 py-1.5 text-sm hover:bg-surface-2 ${
                        current ? "bg-surface-2 font-semibold text-primary" : ""
                      }`}
                    >
                      <span className="min-w-0 font-mono break-all">{file.path}</span>
                      <span className="shrink-0 text-xs font-normal text-muted">
                        {t("firmware.files.meta", {
                          count: file.lines,
                          size: formatSize(file.size, i18n.language),
                        })}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="grid min-w-0 gap-3">
            {open ? (
              <>
                <label className="flex items-center gap-2 justify-self-start text-sm">
                  <input
                    type="checkbox"
                    role="switch"
                    aria-checked={wrap}
                    checked={wrap}
                    onChange={(event) => setWrap(event.target.checked)}
                    className="size-4 accent-primary"
                  />
                  {t("firmware.source.wrap")}
                </label>
                {draft ? (
                  <DraftFile
                    key={open.id}
                    version={version}
                    framework={framework}
                    file={open}
                    wrap={wrap}
                  />
                ) : (
                  <SourceFileView key={open.id} file={open} wrap={wrap} />
                )}
              </>
            ) : (
              <p className="rounded-lg border border-dashed border-border-strong p-4 text-sm text-muted">
                {t("firmware.files.pick")}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** *Add a file* opens the editor in place; files chosen on the computer go beside it. */
function AddFiles({ version, framework }: Props) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [returning, setReturning] = useState(false);
  const addRef = useRef<HTMLButtonElement>(null);

  // Back on the button once the editor closes and the button is there again.
  useEffect(() => {
    if (!returning) return;
    addRef.current?.focus();
    setReturning(false);
  }, [returning]);

  function close() {
    setAdding(false);
    setReturning(true);
  }

  return (
    <div className="grid min-w-0 gap-3">
      {adding ? (
        <SourceFileEditor version={version} framework={framework} onDone={close} />
      ) : (
        <div className="justify-self-start">
          <button
            ref={addRef}
            type="button"
            onClick={() => setAdding(true)}
            className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
          >
            {t("firmware.files.addFile")}
          </button>
        </div>
      )}
      <AddFilesFromDisk version={version} />
    </div>
  );
}

/**
 * A draft's file: *Edit* turns it into the editor in place, and *Save* or *Cancel* turns it
 * back, focus on *Edit* again; *Remove* asks in place first, focus on *Keep*, so a stray Enter
 * keeps the file. The file keeps its id through a rename, so this stays mounted while the
 * version refetches.
 */
function DraftFile({
  version,
  framework,
  file,
  wrap,
}: Props & { file: SourceFile; wrap: boolean }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"view" | "edit" | "remove">("view");
  const editRef = useRef<HTMLButtonElement>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const [focusOn, setFocusOn] = useState<"edit" | "remove" | "keep" | null>(null);

  useEffect(() => {
    if (!focusOn) return;
    ({ edit: editRef, remove: removeRef, keep: keepRef })[focusOn].current?.focus();
    setFocusOn(null);
  }, [focusOn]);

  function show(next: typeof mode, focus: typeof focusOn) {
    setMode(next);
    setFocusOn(focus);
  }

  if (mode === "edit") {
    return (
      <div id={anchorOf(file)} className="min-w-0">
        <SourceFileEditor
          version={version}
          framework={framework}
          file={file}
          onDone={() => show("view", "edit")}
        />
      </div>
    );
  }

  return (
    <SourceFileView file={file} wrap={wrap}>
      {mode === "view" ? (
        <div className="flex flex-wrap gap-2">
          <button
            ref={editRef}
            type="button"
            aria-label={t("firmware.files.editFile", { path: file.path })}
            onClick={() => show("edit", null)}
            className={action}
          >
            {t("firmware.files.edit")}
          </button>
          <button
            ref={removeRef}
            type="button"
            aria-label={t("firmware.files.removeFile", { path: file.path })}
            onClick={() => show("remove", "keep")}
            className={`${action} border-crit text-crit`}
          >
            {t("firmware.files.remove")}
          </button>
        </div>
      ) : (
        <RemoveQuestion
          version={version}
          file={file}
          keepRef={keepRef}
          onKeep={() => show("view", "remove")}
        />
      )}
    </SourceFileView>
  );
}

type RemoveProps = {
  version: FirmwareVersion;
  file: SourceFile;
  keepRef: RefObject<HTMLButtonElement | null>;
  onKeep: () => void;
};

function RemoveQuestion({ version, file, keepRef, onKeep }: RemoveProps) {
  const { t } = useTranslation();
  const remove = useRemoveSourceFile();
  const refusal = remove.error instanceof FirmwareRefusal ? remove.error : null;
  const key = refusalKey(refusal?.code ?? null);

  return (
    <div className="grid justify-items-start gap-1">
      <p className="text-sm">{t("firmware.files.removeQuestion", { path: file.path })}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ versionId: version.id, fileId: file.id })}
          className={`${action} border-crit text-crit`}
        >
          {t("firmware.files.removeConfirm")}
        </button>
        <button ref={keepRef} type="button" onClick={onKeep} className={action}>
          {t("firmware.files.keep")}
        </button>
      </div>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {key ? t(key, { item: refusal?.item ?? "" }) : t("firmware.files.removeError")}
        </p>
      )}
    </div>
  );
}

type FileProps = { file: SourceFile; wrap: boolean };

/**
 * One file as stored. *Copy* follows its size and line count, on a draft and on a release alike
 * (requirement 3.4), and a draft's actions go in CHILDREN after it.
 */
function SourceFileView({ file, wrap, children }: FileProps & { children?: ReactNode }) {
  const { t, i18n } = useTranslation();
  const pathId = useId();
  // Whichever box shows the text, plain or highlighted, so Copy selects in the one on screen.
  const box = useRef<HTMLPreElement>(null);

  return (
    <section id={anchorOf(file)} aria-labelledby={pathId} className="grid min-w-0 gap-1">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 id={pathId} className="font-mono text-sm font-semibold break-all">
          {file.path}
        </h4>
        <p className="text-xs text-muted">
          {t("firmware.files.meta", {
            count: file.lines,
            size: formatSize(file.size, i18n.language),
          })}
        </p>
        <CopyButton file={file} box={box} />
        {children}
      </div>
      <FileText file={file} labelledBy={pathId} wrap={wrap} boxRef={box} />
    </section>
  );
}

type TextProps = FileProps & { labelledBy: string; boxRef: RefObject<HTMLPreElement | null> };

/**
 * A file's text, its box named by the file's heading LABELLEDBY: plain at once and highlighted
 * once the highlighter arrives (requirement 1.5), plain for good past the highlighter's limits
 * or when it can't load, saying why (requirement 1.4), and a note for an empty file. Neither
 * an empty file nor one past the limits asks for the highlighter.
 */
function FileText({ file, labelledBy, wrap, boxRef }: TextProps) {
  const { t, i18n } = useTranslation();
  const shown = { file, labelledBy, wrap, boxRef };

  if (file.content === "") return <PlainSource {...shown} />;
  if (!highlightable(file)) {
    const note = t("firmware.source.tooLarge", {
      lines: HIGHLIGHT_LIMITS.lines,
      size: formatSize(HIGHLIGHT_LIMITS.bytes, i18n.language),
    });
    return <PlainSource {...shown} note={note} />;
  }
  return (
    <SourceErrorBoundary fallback={<PlainSource {...shown} note={t("firmware.source.failed")} />}>
      <Suspense fallback={<PlainSource {...shown} />}>
        <SourceView {...shown} />
      </Suspense>
    </SourceErrorBoundary>
  );
}

/** The file's id is a UUID, so the anchor is unique on the page and safe in a URL. */
function anchorOf(file: SourceFile): string {
  return `file-${file.id}`;
}

/** The id of the file the address points at (`#file-<id>`), or null when it names none. */
function fileInHash(): string | null {
  const match = /^#file-(.+)$/.exec(window.location.hash);
  return match?.[1] ?? null;
}

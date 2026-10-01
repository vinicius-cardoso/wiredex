import type { FirmwareVersion, Framework, SourceFile } from "@wiredex/api-client";
import { type ReactNode, type RefObject, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../files/sizes";
import { AddFilesFromDisk } from "./AddFilesFromDisk";
import { FirmwareRefusal, useRemoveSourceFile } from "./firmware";
import { refusalKey } from "./labels";
import { SourceFileEditor } from "./SourceFileEditor";

type Props = { version: FirmwareVersion; framework: Framework };

const action = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

/**
 * A version's source files in the API's order, `.ino` first (requirement 7.10): an index of
 * links when there are several, then each file as a region named by its path, with its size,
 * its line count and its text exactly as stored. 14-firmware-viewer puts its viewer where the
 * `<pre>` is. A draft also shows what it holds against its limits, adds files typed or chosen
 * on the computer, and edits and removes each in place (requirement 11.9).
 */
export function SourceFiles({ version, framework }: Props) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const files = version.files;
  const draft = version.editable;

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

      {files.length > 1 && (
        <nav aria-label={t("firmware.files.index")}>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {files.map((file) => (
              <li key={file.id} className="min-w-0">
                <a
                  href={`#${anchorOf(file)}`}
                  className="font-mono text-sm break-all text-primary hover:underline"
                >
                  {file.path}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {draft && <AddFiles version={version} framework={framework} />}

      {files.map((file) =>
        draft ? (
          <DraftFile key={file.id} version={version} framework={framework} file={file} />
        ) : (
          <SourceFileView key={file.id} file={file} />
        ),
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
function DraftFile({ version, framework, file }: Props & { file: SourceFile }) {
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
    <SourceFileView file={file}>
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

/** One file as stored; a draft's actions go in CHILDREN, beside its size and line count. */
function SourceFileView({ file, children }: { file: SourceFile; children?: ReactNode }) {
  const { t, i18n } = useTranslation();
  const pathId = useId();

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
        {children}
      </div>
      {/* A long line scrolls inside the box, never the page (requirement 11.16). */}
      <pre className="max-h-[32rem] overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-sm leading-relaxed">
        <code>{file.content}</code>
      </pre>
    </section>
  );
}

/** The file's id is a UUID, so the anchor is unique on the page and safe in a URL. */
function anchorOf(file: SourceFile): string {
  return `file-${file.id}`;
}

import type { FirmwareVersion, Framework, SourceFile } from "@wiredex/api-client";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../files/sizes";
import { control } from "../inventory/StockDialog";
import { useAddSourceFiles, useUpdateSourceFile } from "./firmware";
import { firstFilePlaceholder } from "./labels";
import { type FileProblems, fileRefusalOf, roomLeft, storedSize } from "./sourceText";

type Props = {
  version: FirmwareVersion;
  framework: Framework;
  /** The file being edited; none to add one. */
  file?: SourceFile;
  /** Called once the write has landed, or on *Cancel*. */
  onDone: () => void;
};

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

/**
 * A draft's file, typed or pasted (requirement 11.9): its path, a rename when it is edited,
 * and its text in a plain text box (decision 14), sent exactly as typed, tabs and trailing
 * spaces included; only the server reads CRLF as LF (requirement 7.4). Tab moves on to the
 * next control, as in any text box, so the keyboard is never trapped (requirement 11.15). A
 * refusal lands on the field it names, which takes focus.
 */
export function SourceFileEditor({ version, framework, file, onDone }: Props) {
  const { t, i18n } = useTranslation();
  const add = useAddSourceFiles();
  const update = useUpdateSourceFile();
  const write = file ? update : add;
  const pathId = useId();
  const textId = useId();
  const pathRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const [path, setPath] = useState(file?.path ?? "");
  const [content, setContent] = useState(file?.content ?? "");
  const [problems, setProblems] = useState<FileProblems>({});
  const room = roomLeft(version, file);

  useEffect(() => {
    pathRef.current?.focus();
  }, []);

  function refused(found: FileProblems) {
    setProblems(found);
    if (found.path) pathRef.current?.focus();
    else if (found.content) textRef.current?.focus();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (write.isPending) return;
    const found: FileProblems = {};
    if (path.trim() === "") found.path = t("firmware.files.editor.pathRequired");
    if (storedSize(content) > room) {
      found.content = t("firmware.refusal.version_too_large", {
        room: formatSize(Math.max(room, 0), i18n.language),
      });
    }
    if (found.path || found.content) {
      refused(found);
      return;
    }
    setProblems({});
    // The path and the text go as typed: the server normalizes the path and the line endings,
    // and answers a refusal with the path as it was typed.
    const body = { path, content };
    const onError = (error: unknown) => refused(fileRefusalOf(t, error, room, i18n.language));
    if (file) {
      update.mutate(
        { versionId: version.id, fileId: file.id, body },
        { onSuccess: onDone, onError },
      );
    } else {
      add.mutate(
        { versionId: version.id, body: { files: [body] } },
        { onSuccess: onDone, onError },
      );
    }
  }

  const placeholder =
    !file && version.files.length === 0 ? firstFilePlaceholder[framework] : undefined;

  return (
    <form
      noValidate
      onSubmit={submit}
      aria-label={
        file
          ? t("firmware.files.editor.editTitle", { path: file.path })
          : t("firmware.files.editor.addTitle")
      }
      className="grid min-w-0 gap-3 rounded-lg border border-border bg-surface-2 p-3"
    >
      <div className="grid gap-1">
        <label htmlFor={pathId} className="text-sm font-medium">
          {t("firmware.files.editor.path")}
        </label>
        <input
          ref={pathRef}
          id={pathId}
          type="text"
          value={path}
          placeholder={placeholder}
          onChange={(event) => {
            setPath(event.target.value);
            setProblems(({ path: _, ...rest }) => rest);
          }}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          aria-required="true"
          aria-invalid={problems.path ? true : undefined}
          aria-describedby={`${pathId}-hint${problems.path ? ` ${pathId}-error` : ""}`}
          className={`${control} min-w-0 font-mono text-sm`}
        />
        <p id={`${pathId}-hint`} className="text-sm text-muted">
          {t("firmware.files.editor.pathHint")}
        </p>
        {problems.path && (
          <p id={`${pathId}-error`} className="text-sm text-crit">
            {problems.path}
          </p>
        )}
      </div>

      <div className="grid min-w-0 gap-1">
        <label htmlFor={textId} className="text-sm font-medium">
          {t("firmware.files.editor.text")}
        </label>
        {/* No wrapping, so a long line scrolls inside the box, never the page (11.16). */}
        <textarea
          ref={textRef}
          id={textId}
          value={content}
          onChange={(event) => {
            setContent(event.target.value);
            setProblems(({ content: _, ...rest }) => rest);
          }}
          rows={14}
          wrap="off"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={problems.content ? true : undefined}
          aria-describedby={`${textId}-hint${problems.content ? ` ${textId}-error` : ""}`}
          className={`${control} min-w-0 resize-y overflow-auto font-mono text-sm leading-relaxed`}
        />
        <p id={`${textId}-hint`} className="text-sm text-muted">
          {t("firmware.files.editor.textHint", {
            room: formatSize(Math.max(room, 0), i18n.language),
          })}
        </p>
        {problems.content && (
          <p id={`${textId}-error`} className="text-sm text-crit">
            {problems.content}
          </p>
        )}
      </div>

      {problems.form && (
        <p role="alert" className="text-sm text-crit">
          {problems.form}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={write.isPending}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {file ? t("firmware.files.editor.save") : t("firmware.files.editor.add")}
        </button>
        <button type="button" onClick={onDone} className={action}>
          {t("firmware.files.editor.cancel")}
        </button>
      </div>
    </form>
  );
}

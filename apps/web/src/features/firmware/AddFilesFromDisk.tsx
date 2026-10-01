import type { FirmwareVersion } from "@wiredex/api-client";
import { type ChangeEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../files/sizes";
import { useAddSourceFiles } from "./firmware";
import { fileRefusalOf, looksLikeText, roomLeft, storedSize } from "./sourceText";

/**
 * Adds files chosen on the computer to a draft, all in one request, so the write can't half
 * succeed (requirement 7.1, decision 10). Each file's path is its name. A file that isn't text,
 * or files that would pass the version's 100 files or its room left, are refused here before
 * anything is sent, and then none of the chosen files goes (requirement 11.10).
 */
export function AddFilesFromDisk({ version }: { version: FirmwareVersion }) {
  const { t, i18n } = useTranslation();
  const add = useAddSourceFiles();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [added, setAdded] = useState<number | null>(null);
  const room = roomLeft(version);

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const chosen = [...(event.target.files ?? [])];
    if (chosen.length === 0) return;
    setProblem(null);
    setAdded(null);
    const files = await Promise.all(
      chosen.map(async (file) => ({ path: file.name, content: await file.text() })),
    );
    const notText = files.find((file) => !looksLikeText(file.content));
    const size = files.reduce((total, file) => total + storedSize(file.content), 0);
    if (notText) {
      refuse(t("firmware.refusal.not_text", { item: notText.path }));
    } else if (version.files.length + files.length > version.file_limit) {
      refuse(t("firmware.refusal.too_many_files"));
    } else if (size > room) {
      refuse(
        t("firmware.files.disk.tooLarge", {
          size: formatSize(size, i18n.language),
          room: formatSize(Math.max(room, 0), i18n.language),
        }),
      );
    } else {
      add.mutate(
        { versionId: version.id, body: { files } },
        {
          onSuccess: (written) => {
            setAdded(written.length);
            clear();
          },
          onError: (error) => {
            const found = fileRefusalOf(t, error, room, i18n.language);
            refuse(found.path ?? found.content ?? found.form ?? null);
          },
        },
      );
    }
  }

  function refuse(sentence: string | null) {
    setProblem(sentence);
    clear();
  }

  // Emptied, so choosing the same files again, once fixed, is a change again.
  function clear() {
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="grid min-w-0 gap-1">
      <label htmlFor={inputId} className="text-sm font-medium">
        {t("firmware.files.disk.label")}
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        multiple
        disabled={add.isPending}
        onChange={(event) => void choose(event)}
        aria-describedby={`${inputId}-hint`}
        className="min-w-0 text-sm file:mr-3 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-text"
      />
      <p id={`${inputId}-hint`} className="text-sm text-muted">
        {t("firmware.files.disk.hint")}
      </p>
      {problem && (
        <p role="alert" className="text-sm text-crit">
          {problem}
        </p>
      )}
      <p role="status" className="text-sm text-muted">
        {added !== null && t("firmware.files.disk.added", { count: added })}
      </p>
    </div>
  );
}

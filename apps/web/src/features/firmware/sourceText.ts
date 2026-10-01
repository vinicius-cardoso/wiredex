import type { FirmwareVersion, SourceFile } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { formatSize } from "../files/sizes";
import { FirmwareRefusal } from "./firmware";
import { refusalKey } from "./labels";

/** A file's text as the server stores it: CRLF and lone CR read as LF, nothing else touched. */
export function asStored(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** The bytes a text takes in a version, counted as the server counts them (requirement 7.7). */
export function storedSize(text: string): number {
  return new TextEncoder().encode(asStored(text)).length;
}

/**
 * What a version can still take, the file being replaced not counting against it, as its own
 * path doesn't (requirement 7.8).
 */
export function roomLeft(version: FirmwareVersion, replacing?: SourceFile): number {
  return version.size_limit - version.size + (replacing?.size ?? 0);
}

/**
 * Whether text read from a chosen file is text: a NUL marks a binary file, and U+FFFD is what
 * `File.text()` puts where bytes weren't UTF-8 (requirement 11.10).
 */
export function looksLikeText(text: string): boolean {
  return !text.includes("\u0000") && !text.includes("\uFFFD");
}

/** Where a refused file write is shown: on the path, on the text, or for the whole write. */
export type FileProblems = { path?: string; content?: string; form?: string };

/**
 * A refused file write as the sentences the editor shows, on the field the API names
 * (requirements 7.2, 7.3, 7.5); a 404 says the version or the file is gone; the limits and a
 * release are about the whole write. ROOM is what the version had left, which a refusal over
 * its size says.
 */
export function fileRefusalOf(
  t: TFunction,
  error: unknown,
  room: number,
  locale: string,
): FileProblems {
  if (!error) return {};
  const refusal = error instanceof FirmwareRefusal ? error : null;
  if (refusal?.status === 404) return { form: t("firmware.files.editor.gone") };
  const key = refusalKey(refusal?.code ?? null);
  const sentence = key
    ? t(key, { item: refusal?.item ?? "", room: formatSize(Math.max(room, 0), locale) })
    : t("firmware.files.editor.error");
  if (refusal?.field === "path") return { path: sentence };
  if (refusal?.field === "content") return { content: sentence };
  return { form: sentence };
}

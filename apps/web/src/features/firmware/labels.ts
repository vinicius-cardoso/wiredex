import type { FirmwareRefusalCode, Framework, VersionStatus } from "@wiredex/api-client";

/** The frameworks in the order the form offers them (decision 11), *Other* last. */
export const FRAMEWORKS = [
  "arduino",
  "platformio",
  "esp_idf",
  "micropython",
  "other",
] as const satisfies readonly Framework[];

/** Each framework's i18n key, so every screen names a framework the same way. */
export function frameworkKey(framework: Framework) {
  return `firmware.frameworks.${framework}` as const;
}

/** Each version status's i18n key, so the list, the panel and the dialogs say it alike. */
export function statusKey(status: VersionStatus) {
  return `firmware.status.${status}` as const;
}

/** Each status's colour, from the theme tokens: a draft is quiet, a release reads as done. */
export const statusTone: Record<VersionStatus, string> = {
  draft: "text-muted",
  released: "text-ok",
};

/**
 * The path a draft's first file is offered, as each framework's toolchain names its main
 * file (decision 11). *Other* gets a plain C entry point, the commonest of the rest.
 */
export const firstFilePlaceholder: Record<Framework, string> = {
  arduino: "sketch.ino",
  platformio: "src/main.cpp",
  esp_idf: "main/main.c",
  micropython: "main.py",
  other: "main.c",
};

/** Every refusal code has a sentence under `firmware.refusal`. */
const TRANSLATED_REFUSALS = [
  "invalid_name",
  "name_taken",
  "invalid_target",
  "invalid_description",
  "invalid_version",
  "version_taken",
  "invalid_changelog",
  "version_released",
  "no_files",
  "no_changelog",
  "invalid_path",
  "path_taken",
  "not_text",
  "too_many_files",
  "version_too_large",
  "not_released",
  "unit_retired",
  "flashed_in_future",
  "invalid_notes",
  "version_flashed",
  "firmware_flashed",
  "name_in_trash",
] as const satisfies readonly FirmwareRefusalCode[];

/** A refusal code's i18n key, or null for one with no sentence here, which keeps the API's. */
export function refusalKey(code: FirmwareRefusalCode | null) {
  const known = TRANSLATED_REFUSALS.find((translated) => translated === code);
  return known ? (`firmware.refusal.${known}` as const) : null;
}

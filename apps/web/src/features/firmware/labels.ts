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
 * The refusal codes with a sentence under `firmware.refusal`: the firmware's details and a
 * version's number, changelog and release. The files' codes join them with the file editor.
 */
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
] as const satisfies readonly FirmwareRefusalCode[];

/** A refusal code's i18n key, or null for one with no sentence here, which keeps the API's. */
export function refusalKey(code: FirmwareRefusalCode | null) {
  const known = TRANSLATED_REFUSALS.find((translated) => translated === code);
  return known ? (`firmware.refusal.${known}` as const) : null;
}

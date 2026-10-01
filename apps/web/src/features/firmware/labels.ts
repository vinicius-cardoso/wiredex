import type { Framework } from "@wiredex/api-client";

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

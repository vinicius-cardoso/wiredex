import en from "./locales/en.json" with { type: "json" };
import ptBR from "./locales/pt-BR.json" with { type: "json" };

export const languages = ["en", "pt-BR"] as const;
export type Language = (typeof languages)[number];
export type Messages = typeof en;

export const defaultLanguage: Language = "en";

export const languageNames: Record<Language, string> = {
  en: "English",
  "pt-BR": "Português (Brasil)",
};

export const resources = {
  en: { translation: en },
  "pt-BR": { translation: ptBR satisfies Messages },
} as const;

export function isLanguage(value: unknown): value is Language {
  return languages.some((language) => language === value);
}

/** Picks the best supported language from a browser's preference list. */
export function matchLanguage(preferred: readonly string[]): Language {
  for (const tag of preferred) {
    if (isLanguage(tag)) return tag;
    if (tag.toLowerCase().startsWith("pt")) return "pt-BR";
    if (tag.toLowerCase().startsWith("en")) return "en";
  }
  return defaultLanguage;
}

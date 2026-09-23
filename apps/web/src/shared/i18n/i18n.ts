import {
  defaultLanguage,
  isLanguage,
  type Language,
  type Messages,
  matchLanguage,
  resources,
} from "@wiredex/i18n";
import i18next, { type i18n } from "i18next";
import { initReactI18next } from "react-i18next";
import { preferences } from "../lib/storage";

export const LANGUAGE_KEY = "wiredex.language";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: Messages };
  }
}

/** A saved choice wins; otherwise follow the browser. */
export function initialLanguage(browserLanguages: readonly string[]): Language {
  const saved = preferences.read(LANGUAGE_KEY);
  return isLanguage(saved) ? saved : matchLanguage(browserLanguages);
}

export function createI18n(language: Language): i18n {
  const instance = i18next.createInstance();
  void instance.use(initReactI18next).init({
    resources,
    lng: language,
    fallbackLng: defaultLanguage,
    interpolation: { escapeValue: false },
    initAsync: false,
  });
  instance.on("languageChanged", (next) => {
    document.documentElement.lang = next;
  });
  document.documentElement.lang = language;
  return instance;
}

export function saveLanguage(language: Language): void {
  preferences.write(LANGUAGE_KEY, language);
}

import { isLanguage, languageNames, languages } from "@wiredex/i18n";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { saveLanguage } from "./i18n";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const id = useId();

  function change(value: string) {
    if (!isLanguage(value)) return;
    saveLanguage(value);
    void i18n.changeLanguage(value);
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={id} className="text-muted">
        {t("language.label")}
      </label>
      <select
        id={id}
        value={i18n.language}
        onChange={(event) => change(event.target.value)}
        className="rounded-md border border-border-strong bg-surface px-2 py-1 text-text"
      >
        {languages.map((language) => (
          <option key={language} value={language}>
            {languageNames[language]}
          </option>
        ))}
      </select>
    </div>
  );
}

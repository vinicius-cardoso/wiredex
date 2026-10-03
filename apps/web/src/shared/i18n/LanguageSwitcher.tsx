import { isLanguage, languageNames, languages } from "@wiredex/i18n";
import { useTranslation } from "react-i18next";
import { iconButton } from "../ui/icons";
import { saveLanguage } from "./i18n";

/**
 * One button for the language, to keep the header on one line: it shows the language in use
 * as its two letters (EN, PT), and a click moves to the next. Its name spells both out.
 */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const current = isLanguage(i18n.language) ? i18n.language : languages[0];
  const next = languages[(languages.indexOf(current) + 1) % languages.length] ?? current;
  const name = t("language.switch", {
    current: languageNames[current],
    next: languageNames[next],
  });

  function change() {
    saveLanguage(next);
    void i18n.changeLanguage(next);
  }

  return (
    <button
      type="button"
      aria-label={name}
      title={name}
      onClick={change}
      className={`${iconButton} text-xs font-semibold`}
    >
      {current.slice(0, 2).toUpperCase()}
    </button>
  );
}

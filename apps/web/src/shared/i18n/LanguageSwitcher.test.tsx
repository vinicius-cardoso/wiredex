import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider, useTranslation } from "react-i18next";
import { afterEach, describe, expect, it } from "vitest";
import { createI18n, initialLanguage, LANGUAGE_KEY } from "./i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";

function Title() {
  const { t } = useTranslation();
  return <h1>{t("dashboard.title")}</h1>;
}

afterEach(() => {
  localStorage.clear();
});

describe("LanguageSwitcher", () => {
  it("switches the interface language and remembers the choice", async () => {
    render(
      <I18nextProvider i18n={createI18n("en")}>
        <Title />
        <LanguageSwitcher />
      </I18nextProvider>,
    );
    expect(screen.getByRole("heading")).toHaveTextContent("Dashboard");

    await userEvent.selectOptions(screen.getByLabelText("Language"), "pt-BR");

    expect(screen.getByRole("heading")).toHaveTextContent("Painel");
    expect(document.documentElement.lang).toBe("pt-BR");
    expect(localStorage.getItem(LANGUAGE_KEY)).toBe("pt-BR");
  });
});

describe("initialLanguage", () => {
  it("prefers the saved choice over the browser", () => {
    localStorage.setItem(LANGUAGE_KEY, "en");
    expect(initialLanguage(["pt-BR"])).toBe("en");
  });

  it("follows the browser when nothing valid is saved", () => {
    localStorage.setItem(LANGUAGE_KEY, "klingon");
    expect(initialLanguage(["pt-BR"])).toBe("pt-BR");
  });
});

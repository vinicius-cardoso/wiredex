import { render } from "@testing-library/react";
import type { Language } from "@wiredex/i18n";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { createI18n } from "../shared/i18n/i18n";
import { ThemeProvider } from "../shared/theme/ThemeProvider";

export function renderWithProviders(ui: ReactElement, { language = "en" as Language } = {}) {
  return render(
    <I18nextProvider i18n={createI18n(language)}>
      <ThemeProvider>{ui}</ThemeProvider>
    </I18nextProvider>,
  );
}

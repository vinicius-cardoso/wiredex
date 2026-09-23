import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { Language } from "@wiredex/i18n";
import type { ReactElement } from "react";
import { AppProviders } from "../app/providers";
import { createI18n } from "../shared/i18n/i18n";

export function renderWithProviders(ui: ReactElement, { language = "en" as Language } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AppProviders i18n={createI18n(language)} queryClient={queryClient}>
      {ui}
    </AppProviders>,
  );
}

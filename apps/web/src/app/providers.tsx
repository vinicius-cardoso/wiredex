import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { i18n } from "i18next";
import type { ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import { ThemeProvider } from "../shared/theme/ThemeProvider";

export function createQueryClient() {
  return new QueryClient();
}

type Props = { i18n: i18n; queryClient: QueryClient; children: ReactNode };

export function AppProviders({ i18n, queryClient, children }: Props) {
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{children}</ThemeProvider>
      </QueryClientProvider>
    </I18nextProvider>
  );
}

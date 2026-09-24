import "@fontsource-variable/oxanium";
import "@fontsource-variable/manrope";
import "@fontsource-variable/roboto-mono";
import "./styles.css";

import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppProviders, createQueryClient } from "./app/providers";
import { createAppRouter } from "./app/router";
import { createI18n, initialLanguage } from "./shared/i18n/i18n";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

const i18n = createI18n(initialLanguage(navigator.languages));
const queryClient = createQueryClient();

createRoot(container).render(
  <StrictMode>
    <AppProviders i18n={i18n} queryClient={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </AppProviders>
  </StrictMode>,
);

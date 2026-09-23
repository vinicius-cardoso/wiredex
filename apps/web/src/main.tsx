import "@fontsource-variable/oxanium";
import "@fontsource-variable/manrope";
import "@fontsource-variable/roboto-mono";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <h1 className="font-display text-3xl text-primary">Wiredex</h1>
  </StrictMode>,
);

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetMatchMedia } from "./match-media";

afterEach(() => {
  cleanup();
  resetMatchMedia();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

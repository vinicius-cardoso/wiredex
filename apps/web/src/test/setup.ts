import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { resetMatchMedia } from "./match-media";
import { server } from "./server";

// A file's first render of the whole app router imports every page, which takes over the
// default second when `make check` runs every package's tests at once. A real failure still
// fails, just later.
configure({ asyncUtilTimeout: 3_000 });

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMatchMedia();
  localStorage.clear();
  // A file opened in a version's files stays in the address, as it would for a reader.
  window.location.hash = "";
  delete document.documentElement.dataset.theme;
});

afterAll(() => {
  server.close();
});

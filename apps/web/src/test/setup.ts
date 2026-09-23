import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { resetMatchMedia } from "./match-media";
import { server } from "./server";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMatchMedia();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterAll(() => {
  server.close();
});

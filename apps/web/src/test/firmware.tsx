import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { createAppRouter } from "../app/router";
import { createTestQueryClient, renderWithProviders } from "./render";
import {
  aFirmware,
  aSourceFile,
  aVersion,
  respondAsLoggedIn,
  respondWithApiVersion,
  versionSummaryOf,
} from "./server";

/** The weather station of the demo bench, with its three versions (spec 13, decision 15). */
export const FIRMWARE_ID = "0199ffff-0000-7000-8000-000000000001";
export const V100 = "0199ffff-0000-7000-8000-0000000000a1";
export const V110 = "0199ffff-0000-7000-8000-0000000000a2";
export const V120 = "0199ffff-0000-7000-8000-0000000000a3";

export const sketch = aSourceFile({
  id: "0199ffff-0000-7000-8000-0000000000b1",
  path: "weather_station.ino",
  content: '#include "config.h"\n\nvoid setup() {\n\tWire.begin(SDA_PIN, SCL_PIN);  \n}\n',
});

export const config = aSourceFile({
  id: "0199ffff-0000-7000-8000-0000000000b2",
  path: "config.h",
  content: "#define SDA_PIN 21\n#define SCL_PIN 22",
});

export const v100 = aVersion({
  id: V100,
  version: "1.0.0",
  status: "released",
  changelog: "Reads the BME280 every five minutes.",
  released_at: "2026-09-28T10:00:00Z",
  files: [sketch],
});

export const v110 = aVersion({
  id: V110,
  version: "1.1.0",
  status: "released",
  changelog: "Sleeps between readings.\nMoves the pins into config.h.",
  based_on: { id: V100, version: "1.0.0" },
  released_at: "2026-09-29T10:00:00Z",
  files: [sketch, config],
});

export const v120 = aVersion({
  id: V120,
  version: "1.2.0",
  changelog: "Averages three readings.",
  based_on: { id: V110, version: "1.1.0" },
  files: [sketch, config],
});

/**
 * A blink sketch's files for comparing (spec 14): `changed` is `sketch` with a line changed and
 * two added, `source` takes `header`'s place, and `notes` stays as it is. No weather station
 * version changes a file's text, so a changed file comes from here.
 */
export const blink = {
  sketch: aSourceFile({
    id: "0199ffff-0000-7000-8000-0000000000c1",
    path: "app.ino",
    content:
      '#include "util.h"\n// Blinks the LED.\nvoid setup() {}\n\nvoid loop() {\n  delay(100);\n}\n',
  }),
  changed: aSourceFile({
    id: "0199ffff-0000-7000-8000-0000000000c2",
    path: "app.ino",
    content:
      '#include "util.h"\n// Blinks the LED.\nvoid setup() {}\n\nvoid loop() {\n  delay(250);\n  if (ready()) return;\n  blink();\n}\n',
  }),
  header: aSourceFile({
    id: "0199ffff-0000-7000-8000-0000000000c3",
    path: "util.h",
    content: "#define LED 2\n",
  }),
  source: aSourceFile({
    id: "0199ffff-0000-7000-8000-0000000000c4",
    path: "util.cpp",
    content: '#include "util.h"\nint led = LED;\n',
  }),
  notes: aSourceFile({
    id: "0199ffff-0000-7000-8000-0000000000c5",
    path: "notes.txt",
    content: "Pin 2 is the onboard LED.\n",
  }),
};

/**
 * The code a file's box shows, without the line numbers beside it: what a reader selects,
 * whether the box is still plain or already highlighted, so a test checks it character for
 * character, tabs, trailing spaces and the final line break included.
 */
export function codeOf(box: HTMLElement): string {
  const code = box.cloneNode(true) as HTMLElement;
  for (const hidden of code.querySelectorAll('[aria-hidden="true"]')) hidden.remove();
  return code.textContent ?? "";
}

/** The weather station's page listing VERSIONS, highest first, as the API answers it. */
export function weatherStationWith(versions: ReturnType<typeof aVersion>[]) {
  const latest = versions.find((version) => version.status === "released");
  return aFirmware({
    id: FIRMWARE_ID,
    name: "Weather station",
    versions: versions.map(versionSummaryOf),
    latest_release: latest ? { id: latest.id, version: latest.version } : null,
    suggested_version: "1.2.1",
  });
}

/** The app at PATH, logged in; the test answers the firmware and its versions itself. */
export function renderFirmwareAt(path: string) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return router;
}

/** A browser and system recognised in a User-Agent, e.g. Firefox on Linux. */
export type Device = { browser: string; system: string };

// Order matters: Edge and Opera also say "Chrome", and Chrome also says "Safari".
const browsers: [RegExp, string][] = [
  [/Firefox\//, "Firefox"],
  [/Edg(e|A|iOS)?\//, "Edge"],
  [/OPR\//, "Opera"],
  [/Chrome\/|CriOS\//, "Chrome"],
  // "Version/" too: the API keeps 120 characters, which can cut off Safari's last token.
  [/Safari\/|Version\/[\d.]+ /, "Safari"],
];

// Android before Linux, and iPhone/iPad before Mac OS, for the same reason.
const systems: [RegExp, string][] = [
  [/Android/, "Android"],
  [/iPhone|iPad|iPod/, "iOS"],
  [/Windows/, "Windows"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/CrOS/, "ChromeOS"],
  [/Linux/, "Linux"],
];

function firstMatch(userAgent: string, patterns: [RegExp, string][]): string | undefined {
  return patterns.find(([pattern]) => pattern.test(userAgent))?.[1];
}

/** The device behind a User-Agent, or undefined when it isn't a browser we know. */
export function recogniseDevice(userAgent: string): Device | undefined {
  const browser = firstMatch(userAgent, browsers);
  const system = firstMatch(userAgent, systems);
  return browser && system ? { browser, system } : undefined;
}

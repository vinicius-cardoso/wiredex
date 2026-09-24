import { describe, expect, it } from "vitest";
import { recogniseDevice } from "./device";

describe("recogniseDevice", () => {
  it.each([
    [
      "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
      { browser: "Firefox", system: "Linux" },
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
      { browser: "Edge", system: "Windows" },
    ],
    [
      "Mozilla/5.0 (Linux; Android 16; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
      { browser: "Chrome", system: "Android" },
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
      { browser: "Safari", system: "iOS" },
    ],
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
      { browser: "Safari", system: "macOS" },
    ],
    [
      // As stored: the API keeps the first 120 characters.
      "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E1",
      { browser: "Safari", system: "iOS" },
    ],
  ])("recognises %s", (userAgent, device) => {
    expect(recogniseDevice(userAgent)).toEqual(device);
  });

  it("gives up on anything else, such as an app or a script", () => {
    expect(recogniseDevice("Wiredex-Mobile/1.0")).toBeUndefined();
    expect(recogniseDevice("curl/8.16.0")).toBeUndefined();
  });
});

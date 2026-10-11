import { describe, expect, it } from "vitest";
import { commitUrl, repositoryName, shortCommit } from "./git";

describe("a firmware's repository", () => {
  it("is named without its scheme", () => {
    expect(repositoryName("https://github.com/me/station")).toBe("github.com/me/station");
    expect(repositoryName("http://gitea.local:3000/me/blink")).toBe("gitea.local:3000/me/blink");
  });

  it("opens a commit where its host shows one", () => {
    expect(commitUrl("https://github.com/me/station", "a1b2c3d")).toBe(
      "https://github.com/me/station/commit/a1b2c3d",
    );
    expect(commitUrl("https://bitbucket.org/me/station", "a1b2c3d")).toBe(
      "https://bitbucket.org/me/station/commits/a1b2c3d",
    );
  });

  it("shortens a commit to seven digits", () => {
    expect(shortCommit("9fceb02d0ae598e95dc970b74767f19372d61af8")).toBe("9fceb02");
    expect(shortCommit("a1b2c3d")).toBe("a1b2c3d");
  });
});

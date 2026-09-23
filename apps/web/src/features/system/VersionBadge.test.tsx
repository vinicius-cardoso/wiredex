import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import { failApiVersion, respondWithApiVersion } from "../../test/server";
import { shortCommit, webBuild } from "./build-info";
import { VersionBadge } from "./VersionBadge";

describe("VersionBadge", () => {
  it("shows the web version and the API version when they match", async () => {
    respondWithApiVersion(webBuild.version);

    renderWithProviders(<VersionBadge />);

    expect(screen.getByText(`Wiredex v${webBuild.version}`, { exact: false })).toBeInTheDocument();
    expect(await screen.findByText(`API v${webBuild.version}`)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("asks for a reload when the API runs a different version", async () => {
    respondWithApiVersion("9.9.9");

    renderWithProviders(<VersionBadge />);

    expect(await screen.findByRole("status")).toHaveTextContent("A newer version is running");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });

  it("says so when the API cannot be reached", async () => {
    failApiVersion();

    renderWithProviders(<VersionBadge />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });
});

describe("shortCommit", () => {
  it("shortens a git SHA and leaves anything else alone", () => {
    expect(shortCommit("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678")).toBe("a1b2c3d");
    expect(shortCommit("unknown")).toBe("unknown");
  });
});

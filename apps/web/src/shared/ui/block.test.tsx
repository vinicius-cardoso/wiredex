import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Block, type BlockSpan, PageGrid, StackedTable } from "./block";

// Read from disk: Vitest serves every CSS import, `?raw` included, as an empty string unless
// its css option processes the file. A path, not a URL: under jsdom `URL` is jsdom's own,
// which node:fs refuses.
const css = readFileSync(join(import.meta.dirname, "stacked.css"), "utf8");

describe("Block", () => {
  it("is a region named by its h2", () => {
    render(<Block title="Identity">facts</Block>);

    const region = screen.getByRole("region", { name: "Identity" });
    expect(within(region).getByRole("heading", { level: 2, name: "Identity" })).toBeVisible();
    expect(region).toHaveTextContent("facts");
    // Hidden texts inside are placed against the block, not main.
    expect(region).toHaveClass("relative", "min-w-0", "grid-cols-[minmax(0,1fr)]");
  });

  it("takes an h3 inside a group with its own h2", () => {
    render(
      <Block title="Overview" level={3}>
        notes
      </Block>,
    );

    const region = screen.getByRole("region", { name: "Overview" });
    expect(within(region).getByRole("heading", { level: 3, name: "Overview" })).toBeVisible();
    expect(within(region).queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("holds its badge outside its name and its actions inside", () => {
    render(
      <Block
        title="Version 1.2.0"
        badge={<span>Draft</span>}
        actions={<button type="button">Release</button>}
      >
        files
      </Block>,
    );

    const region = screen.getByRole("region", { name: "Version 1.2.0" });
    expect(within(region).getByText("Draft")).toBeVisible();
    expect(within(region).getByRole("button", { name: "Release" })).toBeVisible();
  });

  it("is a navigation named by its heading when it holds links", () => {
    render(
      <Block title="Revisions" as="nav">
        <a href="/a">A</a>
      </Block>,
    );

    const nav = screen.getByRole("navigation", { name: "Revisions" });
    expect(within(nav).getByRole("link", { name: "A" })).toBeVisible();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it.each<[BlockSpan, string[]]>([
    ["full", ["col-span-full"]],
    ["two", ["xl:col-span-2"]],
    ["xl-row", ["xl:col-span-2", "2xl:col-span-1"]],
    ["2xl-two", ["2xl:col-span-2"]],
  ])("spans %s with its classes", (span, classes) => {
    render(
      <Block title="Wide" span={span}>
        content
      </Block>,
    );

    expect(screen.getByRole("region", { name: "Wide" })).toHaveClass(...classes);
  });

  it("takes one cell and one row by default", () => {
    render(<Block title="Small">content</Block>);

    const region = screen.getByRole("region", { name: "Small" });
    expect(region.className).not.toMatch(/col-span|row-span/);
  });

  it("is two rows tall on xl when asked", () => {
    render(
      <Block title="Tall" tallOnXl>
        content
      </Block>,
    );

    expect(screen.getByRole("region", { name: "Tall" })).toHaveClass(
      "xl:row-span-2",
      "2xl:row-span-1",
    );
  });
});

describe("PageGrid", () => {
  it("has three columns on 2xl by default", () => {
    const { container } = render(<PageGrid>blocks</PageGrid>);

    expect(container.firstElementChild).toHaveClass(
      "grid",
      "grid-cols-[minmax(0,1fr)]",
      "xl:grid-cols-2",
      "2xl:grid-cols-3",
    );
  });

  it("stops at two columns when asked", () => {
    const { container } = render(<PageGrid columns={2}>blocks</PageGrid>);

    expect(container.firstElementChild).toHaveClass("xl:grid-cols-2");
    expect(container.firstElementChild).not.toHaveClass("2xl:grid-cols-3");
  });
});

describe("StackedTable", () => {
  it("frames its table, positioned, with the size it reflows below", () => {
    render(
      <StackedTable below="md">
        <table aria-label="Units">
          <tbody>
            <tr>
              <td data-label="Serial">SN-1</td>
            </tr>
          </tbody>
        </table>
      </StackedTable>,
    );

    const table = screen.getByRole("table", { name: "Units" });
    const frame = table.parentElement as HTMLElement;
    expect(frame).toHaveAttribute("data-stack", "md");
    expect(frame).toHaveClass("relative", "min-w-0", "overflow-x-auto");
  });
});

describe("stacked.css", () => {
  it.each(["xs", "sm", "md", "lg"])("reflows the %s frames under a container query", (size) => {
    const rule = new RegExp(`@container \\([^)]*\\)\\s*\\{\\s*\\[data-stack="${size}"\\]`);

    expect(css).toMatch(rule);
  });

  it("makes every frame a container and draws its labels for the eye only", () => {
    expect(css).toMatch(/\[data-stack\]\s*\{\s*container-type: inline-size;/);
    expect(css).toContain('content: attr(data-label) / "";');
    // A field's minimum width would push a card's half-width cell past the frame.
    expect(
      css.match(/:is\(th, td\) :is\(input, select, textarea\) \{\s*min-width: 0;/g),
    ).toHaveLength(4);
  });

  it("is part of the app's stylesheet", () => {
    const styles = readFileSync(join(import.meta.dirname, "../../styles.css"), "utf8");

    expect(styles).toContain('@import "./shared/ui/stacked.css";');
  });
});

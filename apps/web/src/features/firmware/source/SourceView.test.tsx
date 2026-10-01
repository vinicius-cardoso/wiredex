import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SourceFile } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { codeOf, config, sketch } from "../../../test/firmware";
import { aSourceFile } from "../../../test/server";
import { SourceView } from "./SourceView";

/** FILE's view under its heading, as SourceFiles shows it. */
function show(file: SourceFile, wrap = false) {
  const headingId = `heading-${file.path}`;
  const view = (wrapping: boolean) => (
    <section>
      <h4 id={headingId}>{file.path}</h4>
      <SourceView file={file} labelledBy={headingId} wrap={wrapping} />
    </section>
  );
  const rendered = render(view(wrap));
  const box = screen.getByRole("group", { name: file.path });
  return { box, rewrap: (wrapping: boolean) => rendered.rerender(view(wrapping)) };
}

/** The line numbers beside the code, in the order they are shown. */
function numbersIn(box: HTMLElement): HTMLElement[] {
  return [...box.querySelectorAll<HTMLElement>('[aria-hidden="true"]')];
}

describe("SourceView", () => {
  it("numbers each line, the numbers neither read nor selected with the code", () => {
    const { box } = show(sketch);
    const numbers = numbersIn(box);
    expect(numbers.map((number) => number.textContent)).toEqual(["1", "2", "3", "4", "5"]);
    for (const number of numbers) expect(number).toHaveClass("select-none");
    // What is left is the stored text exactly: the tab, the trailing spaces, the final break.
    expect(codeOf(box)).toBe(sketch.content);
  });

  it("keeps a file that ends without a line break as it is, its last line numbered", () => {
    const { box } = show(config);
    expect(numbersIn(box).map((number) => number.textContent)).toEqual(["1", "2"]);
    expect(codeOf(box)).toBe(config.content);
  });

  it("numbers an empty line and a file of one line break as lines of their own", () => {
    const { box } = show(aSourceFile({ path: "notes.txt", content: "a\n\nb\n\n" }));
    expect(numbersIn(box).map((number) => number.textContent)).toEqual(["1", "2", "3", "4"]);
    expect(codeOf(box)).toBe("a\n\nb\n\n");
  });

  it("colours the code from the theme's classes, in the file's language", () => {
    const { box } = show(sketch);
    expect(within(box).getByText('"config.h"')).toHaveClass("tok-string");
    expect(within(box).getByText("void")).toHaveClass("tok-typeName");
    const script = aSourceFile({ path: "boot.py", content: "def main():\n    pass  # later\n" });
    const python = show(script).box;
    expect(within(python).getByText("def")).toHaveClass("tok-keyword");
    expect(within(python).getByText("# later")).toHaveClass("tok-comment");
  });

  it("lets the keyboard reach the box, named by the file's path", async () => {
    const user = userEvent.setup();
    const { box } = show(sketch);
    await user.tab();
    expect(box).toHaveFocus();
    expect(box).toHaveAccessibleName("weather_station.ino");
  });

  it("breaks long lines at the box's width while wrapping, and scrolls them otherwise", () => {
    const { box, rewrap } = show(sketch);
    const code = box.querySelector("code");
    expect(code).not.toHaveClass("whitespace-pre-wrap");
    expect(code).toHaveClass("w-max");
    rewrap(true);
    expect(box.querySelector("code")).toHaveClass("whitespace-pre-wrap");
    expect(box.querySelector("code")).not.toHaveClass("w-max");
    expect(codeOf(box)).toBe(sketch.content);
  });
});

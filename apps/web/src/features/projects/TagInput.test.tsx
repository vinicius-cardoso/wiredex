import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import { TagInput } from "./TagInput";

function Harness({ initial = [] as string[], suggestions = [] as string[] }) {
  const [tags, setTags] = useState(initial);
  return <TagInput label="Tags" value={tags} onChange={setTags} suggestions={suggestions} />;
}

function renderTagInput(props: { initial?: string[]; suggestions?: string[] } = {}) {
  renderWithProviders(<Harness {...props} />);
  return screen.getByRole("combobox", { name: "Tags" });
}

function chips(): string[] {
  const list = screen.queryByRole("list", { name: "Chosen tags" });
  if (!list) return [];
  return within(list)
    .getAllByRole("listitem")
    .map((item) => item.textContent?.replace("×", "") ?? "");
}

describe("TagInput", () => {
  it("adds a tag on Enter, normalized as the server stores it", async () => {
    const box = renderTagInput();

    await userEvent.setup().type(box, "  ＥＳＰ32  {Enter}");

    expect(chips()).toEqual(["esp32"]);
    expect(box).toHaveValue("");
  });

  it("adds a tag on a comma and keeps what follows it typed", async () => {
    const box = renderTagInput();

    await userEvent.setup().type(box, "I2C,outdoor station,gre");

    expect(chips()).toEqual(["i2c", "outdoor station"]);
    expect(box).toHaveValue("gre");
  });

  it("keeps each tag once", async () => {
    const box = renderTagInput({ initial: ["esp32"] });

    await userEvent.setup().type(box, "ESP32{Enter}");

    expect(chips()).toEqual(["esp32"]);
  });

  it("removes the last chip on Backspace in an empty box", async () => {
    const box = renderTagInput({ initial: ["esp32", "i2c"] });

    await userEvent.setup().type(box, "{Backspace}");

    expect(chips()).toEqual(["esp32"]);
  });

  it("removes a chip with its own button", async () => {
    renderTagInput({ initial: ["esp32", "i2c"] });

    await userEvent.setup().click(screen.getByRole("button", { name: "Remove esp32" }));

    expect(chips()).toEqual(["i2c"]);
    expect(screen.getByRole("combobox", { name: "Tags" })).toHaveFocus();
  });

  it("suggests the workspace's tags not chosen yet, picked by the arrow keys", async () => {
    const box = renderTagInput({ initial: ["esp32"], suggestions: ["esp32", "i2c", "indoor"] });
    const user = userEvent.setup();

    await user.type(box, "i");
    const listbox = screen.getByRole("listbox", { name: "Tags" });
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(
      within(listbox)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["i2c", "indoor"]);

    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(within(listbox).getByRole("option", { name: "indoor" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{Enter}");

    expect(chips()).toEqual(["esp32", "indoor"]);
    expect(box).toHaveValue("");
  });

  it("refuses a tag longer than 32 characters and says why", async () => {
    const box = renderTagInput();

    await userEvent.setup().type(box, `${"x".repeat(33)}{Enter}`);

    expect(chips()).toEqual([]);
    expect(screen.getByRole("alert")).toHaveTextContent("A tag has at most 32 characters.");
    expect(box).toHaveAttribute("aria-invalid", "true");
  });

  it("refuses a twenty-first tag", async () => {
    const twenty = Array.from({ length: 20 }, (_, index) => `t${index}`);
    const box = renderTagInput({ initial: twenty });

    await userEvent.setup().type(box, "one more{Enter}");

    expect(chips()).toHaveLength(20);
    expect(screen.getByRole("alert")).toHaveTextContent("A project carries at most 20 tags.");
  });
});

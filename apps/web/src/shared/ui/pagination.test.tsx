import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Language } from "@wiredex/i18n";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import {
  keepSize,
  type PageSize,
  Pagination,
  pageCount,
  pageOfSearch,
  pageWindow,
  slicePage,
  validatePageSearch,
  withPage,
} from "./pagination";

describe("pageWindow", () => {
  it.each([
    [1, 1, [1]],
    [3, 5, [1, 2, 3, 4, 5]],
    [1, 12, [1, 2, "gap", 12]],
    [4, 12, [1, 2, 3, 4, 5, "gap", 12]],
    [6, 12, [1, "gap", 5, 6, 7, "gap", 12]],
    [12, 12, [1, "gap", 11, 12]],
  ])("offers page %i of %i as %j", (page, count, expected) => {
    expect(pageWindow(page, count)).toEqual(expected);
  });
});

describe("validatePageSearch", () => {
  it("keeps a whole page from 2, given as a number or as text", () => {
    expect(validatePageSearch({ page: 2 })).toEqual({ page: 2 });
    expect(validatePageSearch({ page: "3" })).toEqual({ page: 3 });
    expect(validatePageSearch({ page: 100000 })).toEqual({ page: 100000 });
  });

  it.each([1, 0, -1, 2.5, "abc", "", 100001, null])("drops the page %j", (page) => {
    expect(validatePageSearch({ page })).toEqual({});
  });

  it("keeps a size it offers, leaving the default out", () => {
    expect(validatePageSearch({ size: 25 })).toEqual({ size: 25 });
    expect(validatePageSearch({ size: "100" })).toEqual({ size: 100 });
    expect(validatePageSearch({ size: 50 })).toEqual({});
    expect(validatePageSearch({ size: 7 })).toEqual({});
  });

  it("names both keys even when it drops them, so the raw address can't show through", () => {
    const search = validatePageSearch({ page: "abc", size: 7 });

    expect(Object.keys(search).sort()).toEqual(["page", "size"]);
    expect(search).toStrictEqual({ page: undefined, size: undefined });
  });

  it("ignores every other param", () => {
    expect(validatePageSearch({ q: "esp32", page: 4, size: 25 })).toEqual({ page: 4, size: 25 });
  });
});

describe("the address helpers", () => {
  it("fills in the defaults", () => {
    expect(pageOfSearch({})).toEqual({ page: 1, size: 50 });
    expect(pageOfSearch({ page: 3, size: 25 })).toEqual({ page: 3, size: 25 });
  });

  it("sets a page and size, leaving the defaults out and the filters as they are", () => {
    const search = { q: "esp32", page: 4, size: 25 as PageSize };
    expect(withPage(search, 2, 25)).toEqual({ q: "esp32", page: 2, size: 25 });
    expect(withPage(search, 1, 50)).toEqual({ q: "esp32" });
    const unpaged: { q: string; page?: number } = { q: "esp32" };
    expect(withPage(unpaged, 3, 100)).toEqual({ q: "esp32", page: 3, size: 100 });
  });

  it("keeps only the size when a filter starts the list over", () => {
    expect(keepSize({ page: 4, size: 25 })).toEqual({ size: 25 });
    expect(keepSize({ page: 4 })).toEqual({});
  });

  it("counts at least one page", () => {
    expect(pageCount(0, 50)).toBe(1);
    expect(pageCount(50, 50)).toBe(1);
    expect(pageCount(51, 50)).toBe(2);
  });
});

describe("slicePage", () => {
  const items = Array.from({ length: 60 }, (_, index) => index + 1);

  it("cuts out the page asked for", () => {
    expect(slicePage(items, 2, 25)).toEqual({
      items: items.slice(25, 50),
      page: 2,
      total: 60,
    });
  });

  it("serves the last page for one past the end", () => {
    const served = slicePage(items, 9, 25);
    expect(served.page).toBe(3);
    expect(served.items).toEqual([51, 52, 53, 54, 55, 56, 57, 58, 59, 60]);
  });

  it("serves page 1 of an empty list", () => {
    expect(slicePage([], 4, 50)).toEqual({ items: [], page: 1, total: 0 });
  });
});

type BarProps = { total?: number; page?: number; size?: PageSize; language?: Language };

function renderBar({ total = 312, page = 2, size = 50, language = "en" }: BarProps = {}) {
  const onChange = vi.fn();
  renderWithProviders(
    <Pagination
      label="Pages of the parts"
      total={total}
      page={page}
      size={size}
      onChange={onChange}
    />,
    { language },
  );
  return onChange;
}

function bar() {
  return screen.getByRole("navigation", { name: "Pages of the parts" });
}

describe("Pagination", () => {
  it("says which rows are on screen, with an en dash", () => {
    renderBar();

    expect(within(bar()).getByText("51–100 of 312")).toBeInTheDocument();
  });

  it("says it in Portuguese too", () => {
    renderBar({ language: "pt-BR" });

    const nav = screen.getByRole("navigation", { name: "Pages of the parts" });
    expect(within(nav).getByText("51–100 de 312")).toBeInTheDocument();
    expect(within(nav).getByRole("combobox", { name: "Por página" })).toHaveValue("50");
    expect(within(nav).getByRole("button", { name: "Próxima página" })).toBeInTheDocument();
  });

  it("marks the current page, and only that one", () => {
    renderBar();

    const current = within(bar())
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-current") === "page");
    expect(current).toEqual([screen.getByRole("button", { name: "Page 2" })]);
    expect(screen.getByRole("button", { name: "Page 1" })).not.toHaveAttribute("aria-current");
  });

  it("shows the first, the last and the neighbours, with gaps between", () => {
    renderBar({ total: 600, page: 6 });

    const pages = within(bar())
      .getAllByRole("button", { name: /^Page \d+$/ })
      .map((button) => button.textContent);
    expect(pages).toEqual(["1", "5", "6", "7", "12"]);
  });

  it("marks First and Previous as unable to act on page 1", async () => {
    const onChange = renderBar({ page: 1 });

    for (const name of ["First page", "Previous page"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-disabled", "true");
    }
    expect(screen.getByRole("button", { name: "Next page" })).not.toHaveAttribute("aria-disabled");

    await userEvent.setup().click(screen.getByRole("button", { name: "Previous page" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("marks Next and Last as unable to act on the last page", async () => {
    const onChange = renderBar({ page: 7 });

    for (const name of ["Next page", "Last page"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-disabled", "true");
    }
    expect(screen.getByRole("button", { name: "First page" })).not.toHaveAttribute("aria-disabled");

    await userEvent.setup().click(screen.getByRole("button", { name: "Last page" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("asks for the page a number, an arrow or Last points at", async () => {
    const onChange = renderBar({ page: 3 });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Page 4" }));
    expect(onChange).toHaveBeenLastCalledWith(4, 50);
    await user.click(screen.getByRole("button", { name: "Previous page" }));
    expect(onChange).toHaveBeenLastCalledWith(2, 50);
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(onChange).toHaveBeenLastCalledWith(4, 50);
    await user.click(screen.getByRole("button", { name: "First page" }));
    expect(onChange).toHaveBeenLastCalledWith(1, 50);
    await user.click(screen.getByRole("button", { name: "Last page" }));
    expect(onChange).toHaveBeenLastCalledWith(7, 50);
  });

  it("asks for nothing when the current page is clicked", async () => {
    const onChange = renderBar({ page: 3 });

    await userEvent.setup().click(screen.getByRole("button", { name: "Page 3" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps the first row on screen when the size changes", async () => {
    const onChange = renderBar({ page: 3 });
    const user = userEvent.setup();

    // Page 3 at 50 starts at row 101, which page 5 at 25 starts at too.
    await user.selectOptions(screen.getByRole("combobox", { name: "Per page" }), "25");
    expect(onChange).toHaveBeenLastCalledWith(5, 25);
    await user.selectOptions(screen.getByRole("combobox", { name: "Per page" }), "100");
    expect(onChange).toHaveBeenLastCalledWith(2, 100);
  });

  it("works from the keyboard, and keeps focus on Next once it can't go further", async () => {
    const onChange = vi.fn();
    function Paged() {
      const [page, setPage] = useState(1);
      return (
        <Pagination
          label="Pages of the parts"
          total={100}
          page={page}
          size={50}
          onChange={(next, size) => {
            onChange(next, size);
            setPage(next);
          }}
        />
      );
    }
    renderWithProviders(<Paged />);
    const user = userEvent.setup();

    await user.tab();
    expect(screen.getByRole("combobox", { name: "Per page" })).toHaveFocus();
    await user.tab();
    // A button that can't act still takes focus, so the keyboard walks the bar in order.
    expect(screen.getByRole("button", { name: "First page" })).toHaveFocus();
    await user.tab();
    await user.tab();
    await user.tab();
    await user.tab();
    const next = screen.getByRole("button", { name: "Next page" });
    expect(next).toHaveFocus();

    await user.keyboard("{Enter}");

    expect(onChange).toHaveBeenCalledWith(2, 50);
    expect(screen.getByText("51–100 of 100")).toBeInTheDocument();
    expect(next).toHaveFocus();
    expect(next).toHaveAttribute("aria-disabled", "true");
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("shows nothing for an empty list", () => {
    renderBar({ total: 0, page: 1 });

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});

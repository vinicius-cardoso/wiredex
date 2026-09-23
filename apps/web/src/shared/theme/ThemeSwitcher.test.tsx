import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { setSystemDark } from "../../test/match-media";
import { renderWithProviders } from "../../test/render";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { THEME_KEY } from "./theme";

const root = document.documentElement;

describe("ThemeSwitcher", () => {
  it("follows the operating system by default, live", () => {
    renderWithProviders(<ThemeSwitcher />);
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true");
    expect(root.dataset.theme).toBe("light");

    act(() => setSystemDark(true));

    expect(root.dataset.theme).toBe("dark");
  });

  it("applies and remembers an explicit choice", async () => {
    renderWithProviders(<ThemeSwitcher />);

    await userEvent.click(screen.getByRole("button", { name: "Dark" }));

    expect(root.dataset.theme).toBe("dark");
    expect(root.style.colorScheme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("ignores the operating system once light is chosen", async () => {
    renderWithProviders(<ThemeSwitcher />);
    await userEvent.click(screen.getByRole("button", { name: "Light" }));

    act(() => setSystemDark(true));

    expect(root.dataset.theme).toBe("light");
  });

  it("starts from the saved choice", () => {
    localStorage.setItem(THEME_KEY, "dark");

    renderWithProviders(<ThemeSwitcher />);

    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(root.dataset.theme).toBe("dark");
  });
});

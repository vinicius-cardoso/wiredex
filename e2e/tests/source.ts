import type { Locator } from "@playwright/test";

/**
 * The code a source file's box shows, without the line numbers beside it: what a reader selects,
 * whether the box is still plain or already highlighted, so a journey checks it character for
 * character, tabs, trailing spaces and the final line break included.
 */
export function codeOf(box: Locator): Promise<string> {
  return box.evaluate((element) => {
    const code = element.cloneNode(true) as Element;
    for (const hidden of code.querySelectorAll('[aria-hidden="true"]')) hidden.remove();
    return code.textContent ?? "";
  });
}

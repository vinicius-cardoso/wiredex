import type { SourceFile } from "@wiredex/api-client";
import { type RefObject, useState } from "react";
import { useTranslation } from "react-i18next";

const action = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

type Props = { file: SourceFile; box: RefObject<HTMLElement | null> };

/**
 * *Copy* puts the file's stored text on the clipboard, not what the page shows, so neither the
 * line numbers nor the wrapping can leak into it (decision 6, requirement 3.1), and its status
 * says which file it copied (3.2). Where the clipboard is missing, outside a secure context, or
 * refuses, it selects the text in the file's BOX instead and says how to copy it with the
 * keyboard (3.3): the numbers are unselectable, so the browser leaves them out of what Ctrl+C
 * copies. Each file has its own status, beside the button that was used.
 */
export function CopyButton({ file, box }: Props) {
  const { t } = useTranslation();
  const [message, setMessage] = useState<string | null>(null);

  async function copy() {
    try {
      // Outside a secure context there is no navigator.clipboard, so this throws as a refusal.
      await navigator.clipboard.writeText(file.content);
      setMessage(t("firmware.source.copied", { path: file.path }));
    } catch {
      if (box.current) document.getSelection()?.selectAllChildren(box.current);
      setMessage(t("firmware.source.copyByKeyboard", { path: file.path }));
    }
  }

  return (
    <>
      <button
        type="button"
        aria-label={t("firmware.source.copyFile", { path: file.path })}
        onClick={() => void copy()}
        className={action}
      >
        {t("firmware.source.copy")}
      </button>
      {/* Last in the heading's row and a line of its own there, so a message never pushes a
          draft's Edit and Remove aside; while empty it takes no line. */}
      <p role="status" className="order-last basis-full text-sm text-muted empty:basis-auto">
        {message}
      </p>
    </>
  );
}

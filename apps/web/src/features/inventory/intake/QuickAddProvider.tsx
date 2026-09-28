import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { QuickAddDialog, type QuickAddOptions } from "./QuickAddDialog";

export type { QuickAddOptions };

type QuickAdd = {
  /**
   * Opens quick-add, prefilled with whatever the options carry (requirement 2.7). Asked
   * while it is already open, it starts over with the new options.
   */
  open: (options?: QuickAddOptions) => void;
};

const QuickAddContext = createContext<QuickAdd | null>(null);

/** Quick-add, from anywhere under a `QuickAddProvider`: a page, or the palette later. */
export function useQuickAdd(): QuickAdd {
  const quickAdd = use(QuickAddContext);
  if (!quickAdd) throw new Error("useQuickAdd needs a QuickAddProvider above it");
  return quickAdd;
}

type Props = {
  children: ReactNode;
  /** Off while nobody is signed in: then Alt+N does nothing, and neither does `open`. */
  enabled?: boolean;
};

/** One opening of the dialog. The key remounts it when it is asked to start over. */
type Opening = { key: number; options: QuickAddOptions };

/**
 * Holds the one quick-add dialog every page shares, and opens it on Alt+N (requirements 2.2,
 * 2.7; design decision 12).
 *
 * Alt+N is a modifier chord, as WCAG 2.1.4 asks of a shortcut, and not Ctrl+N, which the
 * browser keeps for a new window. It is ignored while typing, since on macOS Option+N is how
 * `ã` is typed, and while any dialog is open, so it never stacks one modal on another. While
 * quick-add is open the page behind it is inert, which makes the dialog modal for the keyboard
 * and for assistive technology alike; closing it puts focus back where it was.
 */
export function QuickAddProvider({ children, enabled = true }: Props) {
  const [opening, setOpening] = useState<Opening | null>(null);
  // Where focus was before the dialog took it, to hand it back on close.
  const returnTo = useRef<HTMLElement | null>(null);
  const isOpen = useRef(false);

  const open = useCallback(
    (options: QuickAddOptions = {}) => {
      if (!enabled) return;
      if (!isOpen.current) {
        const focused = document.activeElement;
        returnTo.current = focused instanceof HTMLElement ? focused : null;
      }
      isOpen.current = true;
      setOpening((current) => ({ key: (current?.key ?? 0) + 1, options }));
    },
    [enabled],
  );

  const close = useCallback(() => {
    isOpen.current = false;
    setOpening(null);
  }, []);

  // After the dialog is gone and the page is no longer inert, so the element can take focus.
  useEffect(() => {
    if (opening !== null) return;
    const target = returnTo.current;
    returnTo.current = null;
    if (target?.isConnected) target.focus();
  }, [opening]);

  // Signing out while it is open closes it, since what it would add has nowhere to go.
  useEffect(() => {
    if (!enabled) close();
  }, [enabled, close]);

  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || !isShortcut(event)) return;
      if (isTyping(event.target) || aDialogIsOpen()) return;
      event.preventDefault();
      open();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [enabled, open]);

  const quickAdd = useMemo(() => ({ open }), [open]);

  return (
    <QuickAddContext value={quickAdd}>
      <div inert={opening !== null}>{children}</div>
      {opening && <QuickAddDialog key={opening.key} options={opening.options} onClose={close} />}
    </QuickAddContext>
  );
}

/**
 * Alt+N and nothing else held. The key is matched first, whatever the layout puts it; when
 * the platform turns Option+N into a dead key (macOS, for the tilde), its physical position is.
 */
function isShortcut(event: KeyboardEvent): boolean {
  if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat) {
    return false;
  }
  return event.key === "n" || event.key === "N" || (event.key === "Dead" && event.code === "KeyN");
}

/** Focus in a field that takes text, where Alt+N is a character to type, not a command. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.closest("input, textarea, select")) return true;
  return target.closest('[contenteditable]:not([contenteditable="false"])') !== null;
}

function aDialogIsOpen(): boolean {
  return document.querySelector('[role="dialog"], [role="alertdialog"], dialog[open]') !== null;
}

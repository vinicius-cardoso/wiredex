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
import { CommandPalette } from "./CommandPalette";

type Palette = {
  /** Opens the palette, focus in its box; asked while it is open, it stays as it is. */
  open: () => void;
};

const PaletteContext = createContext<Palette | null>(null);

/** The palette, from anywhere under a `PaletteProvider`: the header's button, for one. */
export function usePalette(): Palette {
  const palette = use(PaletteContext);
  if (!palette) throw new Error("usePalette needs a PaletteProvider above it");
  return palette;
}

type Props = {
  children: ReactNode;
  /** Off while nobody is signed in: then Ctrl K does nothing, and neither does `open`. */
  enabled?: boolean;
};

/**
 * Holds the one palette every page shares, and opens it on Ctrl K, or ⌘ K on macOS (19's
 * requirements 3.1, 3.5; decision 7 of requirements).
 *
 * The chord types no character, so it opens the palette from a text field too, unlike quick-add's
 * Alt N; it never opens over another dialog, so a modal never stacks on another, and pressed
 * while the palette is open it keeps the browser from taking it. While the palette is open the
 * page behind it is inert, for the keyboard and for assistive technology alike (3.3). Closing it
 * puts focus back where it was, then runs what the choice asked for, a page to open or quick-add,
 * so quick-add finds focus where the owner left it (3.4).
 */
export function PaletteProvider({ children, enabled = true }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  // Where focus was before the palette took it, to hand it back on close.
  const returnTo = useRef<HTMLElement | null>(null);
  // What the choice asked for, run once the palette is gone and focus is back.
  const then = useRef<(() => void) | null>(null);
  const opened = useRef(false);

  const open = useCallback(() => {
    if (!enabled || opened.current) return;
    const focused = document.activeElement;
    returnTo.current = focused instanceof HTMLElement ? focused : null;
    opened.current = true;
    setIsOpen(true);
  }, [enabled]);

  const close = useCallback((after?: () => void) => {
    then.current = after ?? null;
    opened.current = false;
    setIsOpen(false);
  }, []);

  // After the palette is gone and the page is no longer inert, so the element can take focus.
  useEffect(() => {
    if (isOpen) return;
    const target = returnTo.current;
    returnTo.current = null;
    if (target?.isConnected) target.focus();
    const after = then.current;
    then.current = null;
    after?.();
  }, [isOpen]);

  // Signing out while it is open closes it, since nothing it offers is there any more.
  useEffect(() => {
    if (!enabled) close();
  }, [enabled, close]);

  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || !isShortcut(event)) return;
      if (opened.current) {
        event.preventDefault();
        return;
      }
      if (aDialogIsOpen()) return;
      event.preventDefault();
      open();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [enabled, open]);

  const palette = useMemo(() => ({ open }), [open]);

  return (
    <PaletteContext value={palette}>
      <div inert={isOpen}>{children}</div>
      {isOpen && <CommandPalette onClose={close} />}
    </PaletteContext>
  );
}

/** Ctrl K or ⌘ K and nothing else held; the key in either case, as Caps Lock may have it. */
function isShortcut(event: KeyboardEvent): boolean {
  if (event.ctrlKey === event.metaKey || event.altKey || event.shiftKey || event.repeat) {
    return false;
  }
  return event.key === "k" || event.key === "K";
}

function aDialogIsOpen(): boolean {
  return document.querySelector('[role="dialog"], [role="alertdialog"], dialog[open]') !== null;
}

/** Whether the shortcut is ⌘ K here: what the header's button shows (decision 7). */
export function isMac(): boolean {
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}

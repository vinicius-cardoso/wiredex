/** A binary chosen from disk and where in the flash it goes, as typed. */
export type FlashImage = { id: string; name: string; bytes: Uint8Array; offset: string };

/** What the loader is given: the same binary with its offset read. */
export type PlacedImage = { name: string; bytes: Uint8Array; address: number };

/** What the chip said once connected, which the offsets are checked against before a write. */
export type ChipLayout = { bootloaderOffset: number; flashBytes: number | null };

export type ImageProblem =
  | { kind: "empty" | "too_large" | "offset" }
  | { kind: "overlap"; other: string };

export type LayoutRefusal =
  | { kind: "bootloader"; name: string; address: number; expected: number }
  | { kind: "fit"; name: string; flashBytes: number };

/** Flash is erased a sector at a time, so a write that starts inside one would wipe its start. */
export const SECTOR_BYTES = 0x1000;
/** No ESP module carries more flash, so a larger file was picked by mistake. */
export const MAX_IMAGE_BYTES = 64 * 1024 * 1024;

const BOOTLOADER = /bootloader/i;

/**
 * Where a binary usually goes, from its name as the Arduino IDE, PlatformIO and ESP-IDF export
 * it and from the firmware's board. A guess to check, which is why the offset stays editable:
 * the chip itself only confirms the bootloader's (`refusalOf`).
 */
export function suggestedOffset(name: string, board: string): string {
  const chip = board.toLowerCase();
  if (/merged|factory/i.test(name)) return hex(0);
  if (BOOTLOADER.test(name)) {
    if (/esp32-?(c5|p4)/.test(chip)) return hex(0x2000);
    if (/8266|esp32-?(s3|c2|c3|c6|c61|h2)/.test(chip)) return hex(0);
    return hex(0x1000);
  }
  if (/partition/i.test(name)) return hex(0x8000);
  if (/boot_app0|ota_data/i.test(name)) return hex(0xe000);
  // An ESP8266 has no separate bootloader image: its sketch starts the flash.
  return chip.includes("8266") ? hex(0) : hex(0x10000);
}

/** An offset as esptool reads it, `0x10000` or `65536`, or null when it isn't a sector's start. */
export function parseOffset(text: string): number | null {
  const typed = text.trim();
  const digits = /^0x[0-9a-f]{1,8}$/i.test(typed) || /^\d{1,10}$/.test(typed);
  if (!digits) return null;
  const address = Number(typed);
  return address <= 0xffff_ffff && address % SECTOR_BYTES === 0 ? address : null;
}

export function hex(address: number): string {
  return `0x${address.toString(16)}`;
}

/**
 * What keeps each binary from being written, by its id: the first of an empty or oversized
 * file, an offset that isn't one, and sharing a sector with a binary listed before it.
 */
export function problemsOf(images: FlashImage[]): Map<string, ImageProblem> {
  const problems = new Map<string, ImageProblem>();
  const placed: { name: string; start: number; end: number }[] = [];
  for (const image of images) {
    const address = parseOffset(image.offset);
    if (image.bytes.length === 0) {
      problems.set(image.id, { kind: "empty" });
    } else if (image.bytes.length > MAX_IMAGE_BYTES) {
      problems.set(image.id, { kind: "too_large" });
    } else if (address === null) {
      problems.set(image.id, { kind: "offset" });
    } else {
      const end = Math.ceil((address + image.bytes.length) / SECTOR_BYTES) * SECTOR_BYTES;
      const other = placed.find((earlier) => address < earlier.end && earlier.start < end);
      if (other) problems.set(image.id, { kind: "overlap", other: other.name });
      placed.push({ name: image.name, start: address, end });
    }
  }
  return problems;
}

/** The binaries as the loader takes them, lowest address first, or null while any has a problem. */
export function placed(images: FlashImage[]): PlacedImage[] | null {
  if (problemsOf(images).size > 0) return null;
  return images
    .map((image) => ({
      name: image.name,
      bytes: image.bytes,
      address: parseOffset(image.offset) ?? 0,
    }))
    .sort((a, b) => a.address - b.address);
}

/**
 * Why these binaries must not go onto the chip that answered: a bootloader away from where
 * this chip starts, which would leave it unable to boot, or a binary past the end of its flash.
 */
export function refusalOf(images: PlacedImage[], chip: ChipLayout): LayoutRefusal | null {
  for (const image of images) {
    if (BOOTLOADER.test(image.name) && image.address !== chip.bootloaderOffset) {
      return {
        kind: "bootloader",
        name: image.name,
        address: image.address,
        expected: chip.bootloaderOffset,
      };
    }
    if (chip.flashBytes !== null && image.address + image.bytes.length > chip.flashBytes) {
      return { kind: "fit", name: image.name, flashBytes: chip.flashBytes };
    }
  }
  return null;
}

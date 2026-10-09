import type { ESPLoader, FlashSizeValues } from "esptool-js";
import type { ChipLayout, PlacedImage } from "./images";
import { md5 } from "./md5";

/** The ROM loader's own speed, which every chip answers at, and the stub's once it runs. */
const ROM_BAUD = 115_200;
const WRITE_BAUD = 460_800;

export type Chip = ChipLayout & {
  /** As the chip describes itself, such as `ESP32-D0WD-V3 (revision v3.1)`. */
  name: string;
  mac: string | null;
};

export type WriteProgress = { file: number; written: number; total: number };

export type WriteOptions = {
  /** Erase the whole flash first, settings and file systems too, rather than what is written. */
  eraseAll: boolean;
  onProgress: (progress: WriteProgress) => void;
};

/** A chip held in its loader over a serial port, until `restart` or `release` frees the port. */
export type Flasher = {
  chip: Chip;
  /** Writes each binary and reads its checksum back from the flash, failing on a mismatch. */
  write: (images: PlacedImage[], options: WriteOptions) => Promise<void>;
  /** Resets the chip into what was written, then frees the port. */
  restart: () => Promise<void>;
  /** Frees the port and leaves the chip as it is. */
  release: () => Promise<void>;
};

/** Web Serial exists in Chromium on a computer, on a secure page: not Firefox, Safari or phones. */
export function serialSupported(): boolean {
  return typeof navigator !== "undefined" && "serial" in navigator;
}

/**
 * The port the browser's own chooser gave, or null when it was closed without one. It must be
 * asked from a click: the browser refuses it anywhere else.
 */
export async function choosePort(): Promise<SerialPort | null> {
  try {
    return await navigator.serial.requestPort();
  } catch (error) {
    if (error instanceof DOMException && error.name === "NotFoundError") return null;
    throw error;
  }
}

/**
 * Resets the chip on PORT into its loader and reads what it is. esptool-js and its loader
 * stubs load here, in a chunk of their own, so only someone flashing pays for them. LOG takes
 * the loader's own lines, as esptool prints them.
 */
export async function connect(port: SerialPort, log: (line: string) => void): Promise<Flasher> {
  const { ESPLoader, Transport } = await import("esptool-js");
  const transport = new Transport(port, false);
  const loader = new ESPLoader({
    transport,
    baudrate: WRITE_BAUD,
    romBaudrate: ROM_BAUD,
    terminal: { clean: () => {}, write: log, writeLine: log },
  });

  async function release() {
    // A port that never opened, or that the cable left, has nothing to close.
    await transport.disconnect().catch(() => {});
  }

  let name: string;
  try {
    name = await loader.main();
  } catch (error) {
    await release();
    throw error;
  }

  return {
    chip: {
      name,
      // Neither is readable from a chip in secure download mode, and neither is needed to write.
      mac: await loader.chip.readMac(loader).catch(() => null),
      flashBytes: await flashBytesOf(loader),
      bootloaderOffset: loader.chip.BOOTLOADER_FLASH_OFFSET,
    },
    write: (images, { eraseAll, onProgress }) =>
      loader.writeFlash({
        fileArray: images.map((image) => ({ data: image.bytes, address: image.address })),
        // The build already set these in the image's header: write it byte for byte.
        flashMode: "keep",
        flashFreq: "keep",
        flashSize: "keep",
        eraseAll,
        compress: true,
        reportProgress: (file, written, total) => onProgress({ file, written, total }),
        calculateMD5Hash: md5,
      }),
    restart: async () => {
      try {
        await loader.after("hard_reset");
      } finally {
        await release();
      }
    },
    release,
  };
}

async function flashBytesOf(loader: ESPLoader): Promise<number | null> {
  try {
    const size = await loader.detectFlashSize();
    const bytes = size ? loader.flashSizeBytes(size as FlashSizeValues) : -1;
    return bytes > 0 ? bytes : null;
  } catch {
    return null;
  }
}

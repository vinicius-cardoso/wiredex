import { hex, MAX_IMAGE_BYTES } from "./images";

/** A version's stored build, read from its zip: what built it and the binaries to write. */
export type Bundle = {
  board: string;
  tool: string;
  builtAt: string;
  images: { name: string; bytes: Uint8Array; offset: string }[];
};

/** Why a zip isn't a build this dialog can write (spec 20, requirement 2.2). */
export class BundleError extends Error {
  constructor(
    readonly kind: "not_zip" | "no_manifest" | "manifest" | "format" | "missing" | "too_large",
    /** The binary the problem is with, when it is one's. */
    readonly file: string | null = null,
  ) {
    super(kind);
  }
}

/** The manifest's own version. A newer one may place binaries in ways this reader can't. */
const FORMAT = 1;
const MANIFEST = "manifest.json";
/** More binaries than any build has: a zip listing more is not a build. */
const MAX_IMAGES = 32;

const END_OF_DIRECTORY = 0x06054b50;
const DIRECTORY_ENTRY = 0x02014b50;
const LOCAL_HEADER = 0x04034b50;
const STORED = 0;
const DEFLATED = 8;

type Entry = { method: number; packed: number; size: number; header: number };

/**
 * Reads a build's zip: `manifest.json`, then each binary it names, with its offset. The zip is
 * read here, not by the API (decision 2), with the browser's own inflate, which every browser
 * that has Web Serial has. Sizes are checked against the directory before and after inflating,
 * so a zip that claims little and unpacks to much stops at the claim.
 */
export async function readBundle(zip: Uint8Array): Promise<Bundle> {
  const entries = directoryOf(zip);
  const manifestEntry = entries.get(MANIFEST);
  if (!manifestEntry) throw new BundleError("no_manifest");
  const manifest = manifestOf(await contentOf(zip, manifestEntry, MANIFEST));

  const images = [];
  for (const { file, offset } of manifest.images) {
    const entry = entries.get(file);
    if (!entry) throw new BundleError("missing", file);
    images.push({ name: file, bytes: await contentOf(zip, entry, file), offset: hex(offset) });
  }
  return { board: manifest.board, tool: manifest.tool, builtAt: manifest.builtAt, images };
}

type Manifest = Omit<Bundle, "images"> & { images: { file: string; offset: number }[] };

function manifestOf(bytes: Uint8Array): Manifest {
  let read: unknown;
  try {
    read = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new BundleError("manifest");
  }
  if (typeof read !== "object" || read === null) throw new BundleError("manifest");
  const { format, board, tool, built_at: builtAt, images } = read as Record<string, unknown>;
  if (format !== FORMAT) throw new BundleError(typeof format === "number" ? "format" : "manifest");
  if (!Array.isArray(images) || images.length === 0 || images.length > MAX_IMAGES) {
    throw new BundleError("manifest");
  }
  return {
    board: typeof board === "string" ? board : "",
    tool: typeof tool === "string" ? tool : "",
    builtAt: typeof builtAt === "string" ? builtAt : "",
    images: images.map((image: unknown) => {
      const { file, offset } = (image ?? {}) as Record<string, unknown>;
      const placed = typeof file === "string" && file !== "" && Number.isSafeInteger(offset);
      if (!placed || (offset as number) < 0) throw new BundleError("manifest");
      return { file: file as string, offset: offset as number };
    }),
  };
}

/** The zip's central directory, by file name: where each entry's bytes are and how large. */
function directoryOf(zip: Uint8Array): Map<string, Entry> {
  const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  // The end record is the last thing in a zip, but for a comment of up to 65,535 bytes.
  let end = zip.length - 22;
  const stop = Math.max(0, end - 0xffff);
  while (end >= stop && view.getUint32(end, true) !== END_OF_DIRECTORY) end--;
  if (end < stop || end < 0) throw new BundleError("not_zip");

  const entries = new Map<string, Entry>();
  let at = view.getUint32(end + 16, true);
  for (let index = view.getUint16(end + 10, true); index > 0; index--) {
    if (at + 46 > zip.length || view.getUint32(at, true) !== DIRECTORY_ENTRY) {
      throw new BundleError("not_zip");
    }
    const nameLength = view.getUint16(at + 28, true);
    const name = new TextDecoder().decode(zip.subarray(at + 46, at + 46 + nameLength));
    entries.set(name, {
      method: view.getUint16(at + 10, true),
      packed: view.getUint32(at + 20, true),
      size: view.getUint32(at + 24, true),
      header: view.getUint32(at + 42, true),
    });
    at += 46 + nameLength + view.getUint16(at + 30, true) + view.getUint16(at + 32, true);
  }
  return entries;
}

async function contentOf(zip: Uint8Array, entry: Entry, name: string): Promise<Uint8Array> {
  if (entry.size > MAX_IMAGE_BYTES) throw new BundleError("too_large", name);
  const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  if (entry.header + 30 > zip.length || view.getUint32(entry.header, true) !== LOCAL_HEADER) {
    throw new BundleError("not_zip");
  }
  // The local header repeats the name and carries its own extra field, of its own length.
  const start =
    entry.header +
    30 +
    view.getUint16(entry.header + 26, true) +
    view.getUint16(entry.header + 28, true);
  const packed = zip.subarray(start, start + entry.packed);
  if (packed.length !== entry.packed) throw new BundleError("not_zip");
  if (entry.method === STORED) return packed.slice();
  if (entry.method !== DEFLATED) throw new BundleError("not_zip");
  return inflate(packed, entry.size, name);
}

/** PACKED inflated to exactly SIZE bytes: past it the zip lied, and reading stops there. */
async function inflate(packed: Uint8Array, size: number, name: string): Promise<Uint8Array> {
  const inflated = new Uint8Array(size);
  const source = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(packed);
      controller.close();
    },
  });
  const reader = source
    .pipeThrough(new DecompressionStream("deflate-raw") as TransformStream<Uint8Array, Uint8Array>)
    .getReader();
  let length = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (length + value.length > size) {
        await reader.cancel();
        throw new BundleError("too_large", name);
      }
      inflated.set(value, length);
      length += value.length;
    }
  } catch (error) {
    throw error instanceof BundleError ? error : new BundleError("not_zip");
  }
  if (length !== size) throw new BundleError("not_zip");
  return inflated;
}

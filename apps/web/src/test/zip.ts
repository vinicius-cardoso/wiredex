import { deflateRawSync } from "node:zlib";

type ZipEntry = { name: string; data: Uint8Array; stored?: boolean; claims?: number };

/**
 * A zip of ENTRIES, deflated unless `stored`, as Python's `zipfile` writes one: local headers,
 * a central directory, an end record. `claims` writes a size the data doesn't have, for a zip
 * that lies. CRCs are left zero: the reader under test checks sizes, not sums.
 */
export function zipOf(entries: ZipEntry[]): Uint8Array {
  const chunks: Uint8Array[] = [];
  const directory: Uint8Array[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = new TextEncoder().encode(entry.name);
    const packed = entry.stored ? entry.data : new Uint8Array(deflateRawSync(entry.data));
    const size = entry.claims ?? entry.data.length;
    const sizes = (view: DataView, at: number) => {
      view.setUint16(at, entry.stored ? 0 : 8, true);
      view.setUint32(at + 10, packed.length, true);
      view.setUint32(at + 14, size, true);
      view.setUint16(at + 18, name.length, true);
    };

    const local = new Uint8Array(30 + name.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, 0x04034b50, true);
    sizes(localView, 8);
    local.set(name, 30);

    const central = new Uint8Array(46 + name.length);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    sizes(centralView, 10);
    centralView.setUint32(42, offset, true);
    central.set(name, 46);

    chunks.push(local, packed);
    directory.push(central);
    offset += local.length + packed.length;
  }
  const directorySize = directory.reduce((sum, entry) => sum + entry.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, entries.length, true);
  endView.setUint16(10, entries.length, true);
  endView.setUint32(12, directorySize, true);
  endView.setUint32(16, offset, true);
  return concat([...chunks, ...directory, end]);
}

/** A build's zip as `wiredex firmware build` writes it: the manifest, then the binaries. */
export function aBuildZip(
  images: { file: string; offset: number; data: Uint8Array }[],
  manifest: Record<string, unknown> = {},
): Uint8Array {
  const written = {
    format: 1,
    board: "esp32:esp32:esp32",
    tool: "arduino-cli 1.4.1",
    built_at: "2026-10-09T21:40:00Z",
    images: images.map(({ file, offset }) => ({ file, offset })),
    ...manifest,
  };
  return zipOf([
    { name: "manifest.json", data: new TextEncoder().encode(JSON.stringify(written)) },
    ...images.map((image) => ({ name: image.file, data: image.data })),
  ]);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const whole = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    whole.set(part, at);
    at += part.length;
  }
  return whole;
}

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { aBuildZip, zipOf } from "../../../test/zip";
import { BundleError, readBundle } from "./bundle";

/** Vitest runs from the web app's folder, and a jsdom module has no file address of its own. */
const FIXTURE = join(process.cwd(), "src/features/firmware/flashing/fixtures/build.zip");

const text = (value: string) => new TextEncoder().encode(value);
const app = { file: "app.bin", offset: 0x10000, data: text("app".repeat(2000)) };

/** The refusal reading ZIP ends in, as its kind and the file it names. */
async function refusalOf(zip: Uint8Array): Promise<[string, string | null]> {
  try {
    await readBundle(zip);
  } catch (error) {
    if (error instanceof BundleError) return [error.kind, error.file];
    throw error;
  }
  throw new Error("the bundle was read");
}

describe("readBundle", () => {
  it("reads what wiredex firmware build wrote: each binary's bytes at its offset", async () => {
    // Written by the Python side's `bundle()`, so the two agree on the format (property 1).
    const zip = new Uint8Array(readFileSync(FIXTURE));
    const bundle = await readBundle(zip);

    expect(bundle).toMatchObject({
      board: "esp32:esp32:esp32",
      tool: "arduino-cli 1.4.1",
      builtAt: "2026-10-09T21:40:00Z",
    });
    expect(bundle.images.map((image) => [image.name, image.offset, image.bytes.length])).toEqual([
      ["blink.ino.bootloader.bin", "0x1000", 200],
      ["blink.ino.partitions.bin", "0x8000", 32],
      ["boot_app0.bin", "0xe000", 256],
      ["blink.ino.bin", "0x10000", 2000],
    ]);
    expect([...(bundle.images[2]?.bytes ?? [])]).toEqual(Array.from({ length: 256 }, (_, i) => i));
    expect(new TextDecoder("latin1").decode(bundle.images[3]?.bytes).slice(0, 8)).toBe("éappéapp");
  });

  it("reads a stored entry as it reads a deflated one", async () => {
    const manifest = { format: 1, images: [{ file: "app.bin", offset: 0 }] };
    const zip = zipOf([
      { name: "manifest.json", data: text(JSON.stringify(manifest)), stored: true },
      { name: "app.bin", data: text("raw"), stored: true },
    ]);
    const bundle = await readBundle(zip);
    expect(new TextDecoder().decode(bundle.images[0]?.bytes)).toBe("raw");
    // What the manifest leaves out is read as blank, not refused: only the binaries matter.
    expect(bundle).toMatchObject({ board: "", tool: "", builtAt: "" });
  });

  it("refuses what isn't a zip, or one with no manifest", async () => {
    expect(await refusalOf(text("%PDF-1.7 not a zip at all, and long enough"))).toEqual([
      "not_zip",
      null,
    ]);
    expect(await refusalOf(new Uint8Array(4))).toEqual(["not_zip", null]);
    expect(await refusalOf(zipOf([{ name: "app.bin", data: text("app") }]))).toEqual([
      "no_manifest",
      null,
    ]);
  });

  it("refuses a manifest it can't follow", async () => {
    const withManifest = (manifest: string) =>
      zipOf([
        { name: "manifest.json", data: text(manifest) },
        { name: "app.bin", data: app.data },
      ]);
    expect(await refusalOf(withManifest("{not json"))).toEqual(["manifest", null]);
    expect(await refusalOf(withManifest("[]"))).toEqual(["manifest", null]);
    expect(await refusalOf(withManifest('{"images": []}'))).toEqual(["manifest", null]);
    expect(await refusalOf(aBuildZip([app], { images: [] }))).toEqual(["manifest", null]);
    expect(
      await refusalOf(aBuildZip([app], { images: [{ file: "app.bin", offset: -4096 }] })),
    ).toEqual(["manifest", null]);
    expect(
      await refusalOf(aBuildZip([app], { images: [{ file: "app.bin", offset: "0x10000" }] })),
    ).toEqual(["manifest", null]);
    // A format from a newer command is said apart, so the sentence can say to update.
    expect(await refusalOf(aBuildZip([app], { format: 2 }))).toEqual(["format", null]);
  });

  it("names the binary the manifest lists and the zip lacks", async () => {
    const zip = aBuildZip([app], {
      images: [
        { file: "app.bin", offset: 0x10000 },
        { file: "boot.bin", offset: 0x1000 },
      ],
    });
    expect(await refusalOf(zip)).toEqual(["missing", "boot.bin"]);
  });

  it("stops at the size the zip claims when it unpacks to more", async () => {
    const manifest = text(JSON.stringify({ format: 1, images: [{ file: "app.bin", offset: 0 }] }));
    const lying = zipOf([
      { name: "manifest.json", data: manifest },
      { name: "app.bin", data: new Uint8Array(100_000), claims: 16 },
    ]);
    expect(await refusalOf(lying)).toEqual(["too_large", "app.bin"]);

    const huge = zipOf([
      { name: "manifest.json", data: manifest },
      { name: "app.bin", data: text("x"), claims: 65 * 1024 * 1024 },
    ]);
    expect(await refusalOf(huge)).toEqual(["too_large", "app.bin"]);

    const short = zipOf([
      { name: "manifest.json", data: manifest },
      { name: "app.bin", data: text("short"), claims: 64 },
    ]);
    expect(await refusalOf(short)).toEqual(["not_zip", null]);
  });
});

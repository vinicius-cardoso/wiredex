import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { md5 } from "./md5";

const text = (value: string) => new TextEncoder().encode(value);

describe("md5", () => {
  it("matches RFC 1321's test suite", () => {
    expect(md5(text(""))).toBe("d41d8cd98f00b204e9800998ecf8427e");
    expect(md5(text("abc"))).toBe("900150983cd24fb0d6963f7d28e17f72");
    expect(md5(text("message digest"))).toBe("f96b697d7cb7938d525a2f31aaf161d0");
    expect(md5(text("12345678901234567890".repeat(4)))).toBe("57edf4a22be3c955ac49da2e2107b67a");
  });

  it("agrees with Node's on every length around a block's edge", () => {
    for (const length of [55, 56, 57, 63, 64, 65, 119, 120, 128, 4096, 70_001]) {
      const bytes = Uint8Array.from({ length }, (_, index) => (index * 31 + 7) & 0xff);
      expect(md5(bytes), `${length} bytes`).toBe(createHash("md5").update(bytes).digest("hex"));
    }
  });
});

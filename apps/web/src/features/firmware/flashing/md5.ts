/** Each round's left rotation, four per group of sixteen (RFC 1321, 3.4). */
const SHIFTS = [
  [7, 12, 17, 22],
  [5, 9, 14, 20],
  [4, 11, 16, 23],
  [6, 10, 15, 21],
].flatMap((group) => Array.from({ length: 16 }, (_, index) => group[index % 4] ?? 0));

const SINES = Array.from({ length: 64 }, (_, index) =>
  Math.floor(Math.abs(Math.sin(index + 1)) * 2 ** 32),
);

/**
 * The MD5 of BYTES in lower-case hex. Not for secrets: it is the checksum an ESP's loader
 * computes over what it wrote, so a flash is compared with its file, and Web Crypto has none.
 */
export function md5(bytes: Uint8Array): string {
  // The message, a 0x80 byte, zeros, then its length in bits, to a multiple of 64 bytes.
  const padded = new Uint8Array((((bytes.length + 8) >>> 6) + 1) << 6);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const words = new DataView(padded.buffer);
  words.setUint32(padded.length - 8, (bytes.length << 3) >>> 0, true);
  words.setUint32(padded.length - 4, Math.floor(bytes.length / 2 ** 29), true);

  const state = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476];
  for (let block = 0; block < padded.length; block += 64) {
    let [a = 0, b = 0, c = 0, d = 0] = state;
    for (let round = 0; round < 64; round += 1) {
      let mixed: number;
      let word: number;
      if (round < 16) {
        mixed = (b & c) | (~b & d);
        word = round;
      } else if (round < 32) {
        mixed = (d & b) | (~d & c);
        word = (5 * round + 1) % 16;
      } else if (round < 48) {
        mixed = b ^ c ^ d;
        word = (3 * round + 5) % 16;
      } else {
        mixed = c ^ (b | ~d);
        word = (7 * round) % 16;
      }
      const sum = (a + mixed + (SINES[round] ?? 0) + words.getUint32(block + word * 4, true)) | 0;
      const shift = SHIFTS[round] ?? 0;
      a = d;
      d = c;
      c = b;
      b = (b + ((sum << shift) | (sum >>> (32 - shift)))) | 0;
    }
    state[0] = ((state[0] ?? 0) + a) | 0;
    state[1] = ((state[1] ?? 0) + b) | 0;
    state[2] = ((state[2] ?? 0) + c) | 0;
    state[3] = ((state[3] ?? 0) + d) | 0;
  }

  const digest = new DataView(new ArrayBuffer(16));
  state.forEach((value, index) => {
    digest.setInt32(index * 4, value, true);
  });
  return Array.from(new Uint8Array(digest.buffer), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** Time-based one-time codes (RFC 6238: HMAC-SHA1, 30-second steps, 6 digits), made the way an authenticator app makes them. */
import { createHmac } from "node:crypto";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

export function base32Decode(text: string): Buffer {
  const clean = text.replace(/[\s=]+/g, "").toUpperCase();
  let bits = "";
  for (const ch of clean) {
    const value = ALPHABET.indexOf(ch);
    if (value < 0) throw new Error(`not base32: ${ch}`);
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

/** The code for a base32 secret at a moment (milliseconds); `steps` moves it forward or back by whole 30-second steps. */
export function totp(secret: string, at: number = Date.now(), steps = 0): string {
  const counter = Math.floor(at / 1000 / 30) + steps;
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", base32Decode(secret)).update(message).digest();
  const offset = mac[mac.length - 1] & 0x0f;
  const number = (mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(number).padStart(6, "0");
}

// RFC 6238 appendix B test vector (SHA-1, secret "12345678901234567890"): 59 seconds gives 94287082, so 6 digits end 287082.
if (totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59_000) !== "287082") throw new Error("the TOTP helper does not match RFC 6238");

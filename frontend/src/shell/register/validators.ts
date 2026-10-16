/**
 * Pure checks for the sign-up wizard. Each returns a problem (a code the screen turns into words, with numbers to
 * show) or null. They only catch typing mistakes early; the server re-checks everything on submit. No country is
 * hard-coded: phone lengths and tax-number formats come from the country data when it has them.
 */
export type Problem = { code: string; params?: Record<string, string | number> } | null;

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const TAX_ID_SHAPE = /^[A-Z0-9][A-Z0-9/\-. ]{2,29}$/;

/** Well-known mail providers, used only to suggest a correction for a typo. */
const KNOWN_DOMAINS = [
  "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "live.com", "msn.com", "aol.com", "mail.com",
  "proton.me", "protonmail.com", "zoho.com", "gmx.com", "yandex.com", "yahoo.co.uk", "hotmail.co.uk", "googlemail.com",
];

export function nameProblem(value: string, what: "name" | "business", low = 2, high = 120): Problem {
  const text = value.trim().replace(/\s+/g, " ");
  if (!text) return { code: `${what}.required` };
  if (text.length < low) return { code: `${what}.short`, params: { min: low } };
  if (text.length > high) return { code: `${what}.long`, params: { max: high } };
  if (!/[\p{L}\p{N}]/u.test(text)) return { code: `${what}.letters` };
  return null;
}

export function emailProblem(value: string): Problem {
  const text = value.trim();
  if (!text) return { code: "email.required" };
  if (text.length > 200 || !EMAIL.test(text)) return { code: "email.invalid" };
  return null;
}

function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let previous = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const kept = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] === b[j - 1] ? 0 : 1));
      previous = kept;
    }
  }
  return row[b.length];
}

/** "Did you mean jane@gmail.com?": the corrected address when the domain is a near miss of a well-known provider, else null. */
export function suggestEmail(value: string): string | null {
  const text = value.trim().toLowerCase();
  if (emailProblem(text)) return null;
  const at = text.lastIndexOf("@");
  const domain = text.slice(at + 1);
  if (KNOWN_DOMAINS.includes(domain) || domain.length < 6) return null;
  const near = KNOWN_DOMAINS.map((d) => ({ d, n: distance(domain, d) })).filter((m) => m.n >= 1 && m.n <= 2).sort((a, b) => a.n - b.n)[0];
  return near ? `${text.slice(0, at)}@${near.d}` : null;
}

export const PHONE_DIGITS = { min: 6, max: 15 };

/** An optional phone number: digits (with spaces, dashes, brackets, a leading +); its length between the bounds. */
export function phoneProblem(value: string, bounds: { min?: number; max?: number } = {}): Problem {
  const text = value.trim();
  if (!text) return null;
  const min = bounds.min ?? PHONE_DIGITS.min;
  const max = bounds.max ?? PHONE_DIGITS.max;
  if (!/^\+?[\d\s\-().]+$/.test(text)) return { code: "phone.chars" };
  const digits = text.replace(/\D/g, "").length;
  if (digits < min) return { code: "phone.short", params: { min } };
  if (digits > max) return { code: "phone.long", params: { max } };
  return null;
}

export function callingProblem(value: string): Problem {
  return /^[1-9]\d{0,2}$/.test(value.trim().replace(/^\+/, "")) ? null : { code: "calling.invalid" };
}

/** Optional. The server's generic shape always applies; the country pack's pattern only when it supplies one. */
export function taxIdProblem(value: string, pattern?: string): Problem {
  const text = value.trim().replace(/\s+/g, " ");
  if (!text) return null;
  if (!TAX_ID_SHAPE.test(text.toUpperCase())) return { code: "tax.shape" };
  if (pattern) {
    try {
      if (!new RegExp(pattern, "i").test(text)) return { code: "tax.pattern" };
    } catch {
      /* a pattern we cannot read is a hint at most: the server decides */
    }
  }
  return null;
}

export interface PasswordRules {
  /** At least 8 characters: required. */
  length: boolean;
  /** 12 or more: recommended, never required. */
  long: boolean;
  /** Not the email address or the part before the @. */
  notEmail: boolean;
}

export function passwordRules(password: string, email: string): PasswordRules {
  const lowered = password.toLowerCase();
  const login = email.trim().toLowerCase();
  const local = login.split("@")[0] ?? "";
  return {
    length: password.length >= 8,
    long: password.length >= 12,
    notEmail: !login || (lowered !== login && !(local.length >= 4 && lowered === local)),
  };
}

/** 0 (empty) to 4 (strong): length and variety only. Whether it is too common is the server's call. */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (new Set(password.toLowerCase()).size <= 2) return 1;
  let score = 1;
  if (password.length >= 8) score += 1;
  if (password.length >= 12 && kinds >= 2) score += 1;
  if (password.length >= 14 || (password.length >= 10 && kinds >= 3)) score += 1;
  return Math.min(score, 4) as 1 | 2 | 3 | 4;
}

export function confirmProblem(password: string, confirm: string): Problem {
  if (!confirm) return { code: "confirm.required" };
  return password === confirm ? null : { code: "confirm.mismatch" };
}

/** The country to preselect, guessed on this device only (browser language region, then time zone): no outside call. */
export function guessCountry(countries: readonly { code: string; zone: string }[], language: string, timeZone: string): string {
  const region = language.split("-").find((part, i) => i > 0 && /^[A-Za-z]{2}$/.test(part))?.toUpperCase();
  if (region && countries.some((c) => c.code === region)) return region;
  return timeZone && timeZone !== "UTC" ? (countries.find((c) => c.zone === timeZone)?.code ?? "") : "";
}

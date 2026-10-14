/** Pure helpers for the second factor and for throttling: no React, no requests (unit-tested in helpers.test.ts). */

/** How long the password step's challenge lasts, as the API sets it. */
export const CHALLENGE_SECONDS = 300;

/** A shared secret in groups of four (`JBSW Y3DP EHPK 3PXP`), easier to read and to type. */
export function groupSecret(secret: string): string {
  return (secret.replace(/\s+/g, "").toUpperCase().match(/.{1,4}/g) ?? []).join(" ");
}

/** Seconds as `m:ss` for a countdown; never negative. */
export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Whole minutes to wait, at least one. */
export function waitMinutes(seconds: number): number {
  return Math.max(1, Math.ceil(seconds / 60));
}

/** What was typed or pasted into the authenticator-code box: digits only, at most six (`123 456` becomes `123456`). */
export function cleanAuthenticatorCode(input: string): string {
  return input.replace(/\D/g, "").slice(0, 6);
}

export function isAuthenticatorCode(input: string): boolean {
  return /^\d{6}$/.test(input.replace(/\s+/g, ""));
}

/** A backup code as the API expects it: lower case, in the form `abcde-fghjk` (spaces and a missing dash are forgiven). */
export function normaliseBackupCode(input: string): string {
  const raw = input.toLowerCase().replace(/[\s-]+/g, "");
  return raw.length === 10 ? `${raw.slice(0, 5)}-${raw.slice(5)}` : input.trim().toLowerCase();
}

export function isBackupCodeFormat(input: string): boolean {
  return /^[a-z0-9]{5}-[a-z0-9]{5}$/.test(normaliseBackupCode(input));
}

/** Either kind of code, for the places that take whichever the person has (switching off, new backup codes). */
export function isAnyCode(input: string): boolean {
  return isAuthenticatorCode(input) || isBackupCodeFormat(input);
}

export function normaliseAnyCode(input: string): string {
  return isAuthenticatorCode(input) ? input.replace(/\s+/g, "") : normaliseBackupCode(input);
}

export type VerifyFailure =
  | { kind: "wrong" }
  | { kind: "expired" }
  | { kind: "throttled"; retryAfter: number }
  | { kind: "other" };

interface ErrorBody {
  error?: unknown;
  message?: unknown;
  retry_after?: unknown;
}

/** Seconds to wait from a 429: the body's `retry_after`, else the `Retry-After` header, else a minute. */
export function retryAfterSeconds(body: unknown, header?: string | null): number {
  const fromBody = Number((body as ErrorBody | null)?.retry_after);
  if (Number.isFinite(fromBody) && fromBody > 0) return Math.ceil(fromBody);
  const fromHeader = Number(header);
  return Number.isFinite(fromHeader) && fromHeader > 0 ? Math.ceil(fromHeader) : 60;
}

/**
 * Which screen state a failed second-factor request means. A 401 whose message says the challenge itself is bad (expired,
 * malformed, not a challenge) sends the person back to the password step; any other 401 is a wrong code.
 */
export function classifyVerifyFailure(status: number, body: unknown, retryAfterHeader?: string | null): VerifyFailure {
  if (status === 429) return { kind: "throttled", retryAfter: retryAfterSeconds(body, retryAfterHeader) };
  if (status === 401) {
    if ((body as { error?: string } | null)?.error === "challenge_expired") return { kind: "expired" };
    const message = String((body as ErrorBody | null)?.message ?? "");
    return /expired|malformed|invalid token|not a sign-in challenge/i.test(message) ? { kind: "expired" } : { kind: "wrong" };
  }
  return { kind: "other" };
}

/** True for the API's "set up two-step verification first" answer. */
export function isSetupRequired(status: number, body: unknown): boolean {
  return status === 403 && (body as ErrorBody | null)?.error === "mfa_setup_required";
}

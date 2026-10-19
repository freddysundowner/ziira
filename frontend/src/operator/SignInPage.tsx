import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  Alert, BrandWord, Button, CHALLENGE_SECONDS, cleanAuthenticatorCode, Field, formatCountdown, Input, isAuthenticatorCode, useCountdown, useTranslation, waitMinutes,
} from "@/sdk";

import { useOperator } from "./session";

/**
 * Platform staff sign in with email and password. When the platform requires a second factor the answer is a challenge and
 * the screen asks for the code from the authenticator app next; otherwise the password alone opens the console.
 */
export function SignInPage() {
  const { t } = useTranslation("operator");
  const { signIn, completeMfa } = useOperator();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<{ value: string; issuedAt: number } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const left = useCountdown(blockedUntil);
  const blocked = blockedUntil !== null && left > 0;
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!challenge) return;
    const id = window.setTimeout(() => back(t("signIn.expired")), Math.max(0, challenge.issuedAt + CHALLENGE_SECONDS * 1000 - Date.now()));
    return () => window.clearTimeout(id);
  }, [challenge, t]);

  useEffect(() => {
    if (challenge && !busy && !blocked) codeInput.current?.focus();
  }, [challenge, busy, blocked]);

  function back(message: string | null = null) {
    setChallenge(null);
    setCode("");
    setPassword("");
    setError(message);
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    if (busy || blocked) return;
    setBusy(true);
    setError(null);
    const result = await signIn(email.trim(), password);
    setBusy(false);
    if ("signedIn" in result) return;               // the console takes over
    if ("challenge" in result) {
      setChallenge({ value: result.challenge, issuedAt: Date.now() });
      return;
    }
    if (result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    setError(result.error);
    setPassword("");
  }

  async function send(value: string) {
    if (!challenge || busy || blocked) return;
    setBusy(true);
    setError(null);
    const result = await completeMfa(challenge.value, value);
    setBusy(false);
    if (result.ok) return;                         // signed in: the console takes over
    if (result.failure === "expired") return back(result.error);
    if (result.failure === "throttled" && result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    setError(result.error);
    setCode("");
  }

  const change = (raw: string) => {
    const clean = cleanAuthenticatorCode(raw);
    setCode(clean);
    if (clean.length === 6 && clean !== code) void send(clean);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-5">
      <main className="w-full max-w-sm space-y-6">
        <div className="flex items-center gap-2.5">
          <BrandWord className="h-9" />
          <div>
            <p className="text-lg font-semibold leading-tight">{t("appName")}</p>
            <p className="text-xs text-muted">{t("staffOnly")}</p>
          </div>
        </div>
        {!challenge ? (
          <form onSubmit={submitPassword} className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-card">
            <h1 className="text-xl font-semibold">{t("signIn.title")}</h1>
            <Field label={t("signIn.email")}>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus required />
            </Field>
            <Field label={t("signIn.password")}>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </Field>
            {blocked && <Alert tone="warn">{t("signIn.wait", { count: waitMinutes(left), time: formatCountdown(left) })}</Alert>}
            {error && !blocked && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" size="lg" loading={busy} disabled={!email || !password || blocked} className="w-full">{t("signIn.continue")}</Button>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); if (isAuthenticatorCode(code)) void send(code); }} className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-card">
            <h1 className="text-xl font-semibold">{t("signIn.codeTitle")}</h1>
            <p className="text-sm text-muted">{t("signIn.codeHint")}</p>
            <Field label={t("signIn.code")}>
              <Input ref={codeInput} value={code} onChange={(e) => change(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" disabled={blocked}
                className="text-center font-mono text-lg tracking-[0.4em]" />
            </Field>
            {blocked && <Alert tone="warn">{t("signIn.wait", { count: waitMinutes(left), time: formatCountdown(left) })}</Alert>}
            {error && !blocked && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" size="lg" loading={busy} disabled={!isAuthenticatorCode(code) || blocked} className="w-full">{t("signIn.verify")}</Button>
            <Button type="button" variant="ghost" className="w-full" onClick={() => back()}>{t("signIn.back")}</Button>
          </form>
        )}
      </main>
    </div>
  );
}

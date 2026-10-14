import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  Alert, Button, cleanAuthenticatorCode, CHALLENGE_SECONDS, Field, formatCountdown, Input, isBackupCodeFormat, isAuthenticatorCode, normaliseBackupCode,
  useCountdown, useSession, useTranslation, waitMinutes,
} from "@/sdk";

/**
 * The second step of signing in: a code from the authenticator app, or a backup code. The challenge from the password step
 * lasts five minutes; when it runs out (or the API says so) the person goes back to the password step.
 */
export function SecondFactor({ challenge, issuedAt, onBack, onExpired }: { challenge: string; issuedAt: number; onBack: () => void; onExpired: () => void }) {
  const { t } = useTranslation();
  const { completeMfa } = useSession();
  const [backup, setBackup] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const left = useCountdown(blockedUntil);
  const blocked = blockedUntil !== null && left > 0;
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const id = window.setTimeout(onExpired, Math.max(0, issuedAt + CHALLENGE_SECONDS * 1000 - Date.now()));
    return () => window.clearTimeout(id);
  }, [issuedAt, onExpired]);

  useEffect(() => {
    if (blockedUntil !== null && left === 0) setBlockedUntil(null);
  }, [blockedUntil, left]);

  useEffect(() => {
    if (!blocked && !busy) input.current?.focus();
  }, [backup, blocked, busy]);

  const valid = backup ? isBackupCodeFormat(code) : isAuthenticatorCode(code);

  async function send(value: string) {
    if (busy || blocked) return;
    setBusy(true);
    setError(null);
    const result = await completeMfa(challenge, backup ? normaliseBackupCode(value) : value);
    setBusy(false);
    if (!result.error) return;                     // signed in: the app takes over
    if (result.failure === "expired") return onExpired();
    if (result.failure === "throttled" && result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    setError(result.failure === "wrong" ? t(backup ? "mfa.wrongBackup" : "mfa.wrongCode") : result.error);
    setCode("");
  }

  const change = (raw: string) => {
    if (backup) return setCode(raw);
    const clean = cleanAuthenticatorCode(raw);
    setCode(clean);
    if (clean.length === 6 && clean !== code) void send(clean);      // six digits typed or pasted: no need to press the button
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) void send(code);
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("mfa.codeTitle")}</h1>
        <p className="text-sm text-muted">{t(backup ? "mfa.backupHint" : "mfa.codeHint")}</p>
      </div>
      <Field label={t(backup ? "mfa.backupLabel" : "mfa.codeLabel")} hint={backup ? t("mfa.backupFormat") : undefined}>
        {backup ? (
          <Input ref={input} value={code} onChange={(e) => change(e.target.value)} autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="abcde-fghjk" disabled={blocked} className="font-mono" />
        ) : (
          <Input ref={input} value={code} onChange={(e) => change(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" disabled={blocked}
            className="text-center font-mono text-lg tracking-[0.4em]" />
        )}
      </Field>
      {blocked && <Alert tone="warn">{t("signIn.waitMinutes", { count: waitMinutes(left) })} {t("signIn.countdown", { time: formatCountdown(left) })}</Alert>}
      {error && !blocked && <Alert tone="bad">{error}</Alert>}
      <Button type="submit" size="lg" loading={busy} disabled={!valid || blocked} className="w-full">{busy ? t("mfa.verifying") : t("mfa.verify")}</Button>
      <p className="text-xs text-muted">{t("mfa.expiresNote")}</p>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="text-sm font-medium text-brand-strong hover:underline" onClick={() => { setBackup(!backup); setCode(""); setError(null); }}>
          {t(backup ? "mfa.useApp" : "mfa.useBackup")}
        </button>
        <Button type="button" variant="ghost" onClick={onBack}>{t("mfa.back")}</Button>
      </div>
    </form>
  );
}

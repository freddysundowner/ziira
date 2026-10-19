import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Button, Field, formatCountdown, IconButton, Input, useCountdown, useSession, useTranslation, waitMinutes } from "@/sdk";
import type { Business } from "@/sdk/session";

import { AuthShell } from "./AuthShell";
import { SecondFactor } from "./SecondFactor";

interface Pending {
  challenge: string;
  /** When the challenge was issued (Date.now()): it lasts five minutes. */
  issuedAt: number;
}

export function SignIn() {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const [choices, setChoices] = useState<Business[]>([]);
  const [typed, setTyped] = useState<{ login: string; password: string } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const left = useCountdown(blockedUntil);
  const blocked = blockedUntil !== null && left > 0;

  useEffect(() => {
    if (blockedUntil !== null && left === 0) setBlockedUntil(null);
  }, [blockedUntil, left]);

  async function attempt(login: string, password: string, workspace?: string) {
    setBusy(true);
    const result = await signIn(login, password, workspace);
    setBusy(false);
    setError(result.error);
    setTyped({ login, password });
    if (result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    if (result.businesses) setChoices(result.businesses);
    if (result.mfaChallenge) setPending({ challenge: result.mfaChallenge, issuedAt: Date.now() });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (blocked) return;
    const form = new FormData(event.currentTarget);
    setChoices([]);
    await attempt(String(form.get("login")).trim(), String(form.get("password")));
  }

  const backToPassword = (message: string | null) => {
    setPending(null);
    setChoices([]);
    setError(message);
  };

  if (pending) {
    return (
      <AuthShell>
        <SecondFactor challenge={pending.challenge} issuedAt={pending.issuedAt} onBack={() => backToPassword(null)} onExpired={() => backToPassword(t("mfa.expired"))} />
      </AuthShell>
    );
  }

  if (choices.length > 0 && typed) {
    return (
      <AuthShell>
        <div className="space-y-3">
          <p className="text-sm text-muted">{t("signIn.choose")}</p>
          {choices.map((b) => (
            <Button key={b.workspace} variant="secondary" size="lg" loading={busy} disabled={blocked} className="w-full justify-start" onClick={() => void attempt(typed.login, typed.password, b.workspace)}>
              {b.name}
            </Button>
          ))}
          {blocked && <Alert tone="warn">{t("signIn.waitMinutes", { count: waitMinutes(left) })} {t("signIn.countdown", { time: formatCountdown(left) })}</Alert>}
          {error && !blocked && <Alert tone="bad">{error}</Alert>}
          <Button variant="ghost" className="w-full" onClick={() => setChoices([])}>{t("register.back")}</Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.04em] sm:text-[34px]">{t("signIn.title")}</h1>
          <p className="text-[15px] leading-relaxed text-muted">{t("signIn.subtitle")}</p>
        </div>
        <fieldset disabled={blocked} className="space-y-5">
          <Field label={t("signIn.login")}><Input name="login" required autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false} defaultValue={typed?.login ?? ""} /></Field>
          <Field label={t("signIn.password")}>
            <div className="relative">
              <Input name="password" type={show ? "text" : "password"} required autoComplete="current-password" className="pr-10" />
              <IconButton label={show ? t("signIn.hide") : t("signIn.show")} className="absolute right-0 top-0 h-12 w-12" onClick={() => setShow(!show)}>
                {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </IconButton>
            </div>
          </Field>
        </fieldset>
        <div className="-mt-3 text-right">
          <Link className="text-sm font-medium text-brand-strong hover:underline" to="/forgot-password">{t("signIn.forgot")}</Link>
        </div>
        {blocked && <Alert tone="warn">{t("signIn.waitMinutes", { count: waitMinutes(left) })} {t("signIn.countdown", { time: formatCountdown(left) })}</Alert>}
        {error && !blocked && <Alert tone="bad">{error}</Alert>}
        <Button type="submit" size="lg" loading={busy} disabled={blocked} className="w-full">{busy ? t("signIn.working") : t("signIn.submit")}</Button>
        <p className="text-center text-sm text-muted">
          {t("signIn.newHere")} <Link className="font-medium text-brand-strong hover:underline" to="/register">{t("signIn.createBusiness")}</Link>
        </p>
      </form>
    </AuthShell>
  );
}

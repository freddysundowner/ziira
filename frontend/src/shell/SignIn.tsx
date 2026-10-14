import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Button, Field, IconButton, Input, useSession, useTranslation } from "@/sdk";
import type { Business } from "@/sdk/session";

import { AuthShell } from "./AuthShell";

export function SignIn() {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const [choices, setChoices] = useState<Business[]>([]);
  const [typed, setTyped] = useState<{ login: string; password: string } | null>(null);

  async function attempt(login: string, password: string, workspace?: string) {
    setBusy(true);
    const result = await signIn(login, password, workspace);
    setBusy(false);
    setError(result.error);
    if (result.businesses) {
      setTyped({ login, password });
      setChoices(result.businesses);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setChoices([]);
    await attempt(String(form.get("login")).trim(), String(form.get("password")));
  }

  if (choices.length > 0 && typed) {
    return (
      <AuthShell>
        <div className="space-y-3">
          <p className="text-sm text-muted">{t("signIn.choose")}</p>
          {choices.map((b) => (
            <Button key={b.workspace} variant="secondary" size="lg" loading={busy} className="w-full justify-start" onClick={() => void attempt(typed.login, typed.password, b.workspace)}>
              {b.name}
            </Button>
          ))}
          {error && <Alert tone="bad">{error}</Alert>}
          <Button variant="ghost" className="w-full" onClick={() => setChoices([])}>{t("register.back")}</Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">{t("signIn.title")}</h1>
          <p className="text-sm text-muted">{t("signIn.subtitle")}</p>
        </div>
        <Field label={t("signIn.login")}><Input name="login" required autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false} /></Field>
        <Field label={t("signIn.password")}>
          <div className="relative">
            <Input name="password" type={show ? "text" : "password"} required autoComplete="current-password" className="pr-10" />
            <IconButton label={show ? t("signIn.hide") : t("signIn.show")} className="absolute right-0 top-0 h-9" onClick={() => setShow(!show)}>
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </IconButton>
          </div>
        </Field>
        {error && <Alert tone="bad">{error}</Alert>}
        <Button type="submit" size="lg" loading={busy} className="w-full">{busy ? t("signIn.working") : t("signIn.submit")}</Button>
        <p className="text-center text-sm text-muted">
          {t("signIn.newHere")} <Link className="font-medium text-brand-strong hover:underline" to="/register">{t("signIn.createBusiness")}</Link>
        </p>
      </form>
    </AuthShell>
  );
}

import { type FormEvent, useState } from "react";

import { Button, ErrorText, Field, Input, useSession, useTranslation } from "@/sdk";
import type { Business } from "@/sdk/session";

export function SignIn() {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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
    await attempt(String(form.get("login")), String(form.get("password")));
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold">{t("signIn.title")}</h1>
        <Field label={t("signIn.login")}><Input name="login" required autoComplete="username" /></Field>
        <Field label={t("signIn.password")}><Input name="password" type="password" required autoComplete="current-password" /></Field>
        <ErrorText>{error}</ErrorText>
        {choices.length > 0 && typed && (
          <div className="space-y-2">
            <p className="text-sm text-slate-600">{t("signIn.choose")}</p>
            {choices.map((b) => (
              <Button key={b.workspace} type="button" disabled={busy} className="w-full"
                onClick={() => void attempt(typed.login, typed.password, b.workspace)}>
                {b.name}
              </Button>
            ))}
          </div>
        )}
        <Button type="submit" disabled={busy} className="w-full">{busy ? t("signIn.working") : t("signIn.submit")}</Button>
      </form>
    </main>
  );
}

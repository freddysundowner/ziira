import { type FormEvent, useState } from "react";

import { Button, ErrorText, Field, Input, useSession, useTranslation } from "@/sdk";

export function SignIn() {
  const { t } = useTranslation();
  const { signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(await signIn(String(form.get("workspace")), String(form.get("login")), String(form.get("password"))));
    setBusy(false);
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold">{t("signIn.title")}</h1>
        <Field label={t("signIn.workspace")}><Input name="workspace" required autoComplete="organization" /></Field>
        <Field label={t("signIn.login")}><Input name="login" required autoComplete="username" /></Field>
        <Field label={t("signIn.password")}><Input name="password" type="password" required autoComplete="current-password" /></Field>
        <ErrorText>{error}</ErrorText>
        <Button type="submit" disabled={busy} className="w-full">{busy ? t("signIn.working") : t("signIn.submit")}</Button>
      </form>
    </main>
  );
}

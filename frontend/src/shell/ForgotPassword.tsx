import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Field, Input, unwrap, useMutation, useTranslation } from "@/sdk";

import { AuthShell } from "./AuthShell";

/** Asks for an emailed link to choose a new password. The API answers the same whether or not the login exists. */
export function ForgotPassword() {
  const { t } = useTranslation();
  const [login, setLogin] = useState("");
  const ask = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/auth/password/forgot", { body: { login: login.trim() } })),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask.mutate();
  };

  if (ask.data) {
    return (
      <AuthShell>
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold">{t("forgot.sentTitle")}</h1>
          <Alert tone="ok">{ask.data.message}</Alert>
          {ask.data.dev_token && (
            <Alert tone="info">
              {t("forgot.devOnly")}{" "}
              <Link className="font-medium underline" to={`/reset-password?token=${encodeURIComponent(ask.data.dev_token)}`}>{t("forgot.devLink")}</Link>
            </Alert>
          )}
          <Link className="text-sm font-medium text-brand-strong hover:underline" to="/">{t("register.backToSignIn")}</Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">{t("forgot.title")}</h1>
          <p className="text-sm text-muted">{t("forgot.hint")}</p>
        </div>
        <Field label={t("signIn.login")}>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} required autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false} />
        </Field>
        {ask.isError && <Alert tone="bad">{ask.error.message}</Alert>}
        <Button type="submit" size="lg" loading={ask.isPending} disabled={!login.trim()} className="w-full">{ask.isPending ? t("forgot.working") : t("forgot.submit")}</Button>
        <p className="text-center text-sm"><Link className="font-medium text-brand-strong hover:underline" to="/">{t("register.backToSignIn")}</Link></p>
      </form>
    </AuthShell>
  );
}

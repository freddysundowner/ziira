import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Alert, ApiError, api, Button, Field, Input, unwrap, useMutation, useTranslation } from "@/sdk";

import { AuthShell } from "./AuthShell";

const MIN_LENGTH = 8;

/** The page the emailed link opens: choose a new password. A refused (for example too easy) password leaves the link usable. */
export function ResetPassword() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const reset = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/auth/password/reset", { body: { token: token ?? "", new_password: password } })),
  });
  const mismatch = confirm !== "" && confirm !== password;
  const ready = password.length >= MIN_LENGTH && password === confirm;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready && !reset.isPending) reset.mutate();
  };

  if (!token) {
    return (
      <AuthShell>
        <div className="space-y-4">
          <Alert tone="bad">{t("reset.badLink")}</Alert>
          <Link className="text-sm font-medium text-brand-strong hover:underline" to="/forgot-password">{t("reset.askNew")}</Link>
        </div>
      </AuthShell>
    );
  }

  if (reset.isSuccess) {
    return (
      <AuthShell>
        <div className="space-y-4">
          <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.04em] sm:text-[34px]">{t("reset.doneTitle")}</h1>
          <Alert tone="ok">{t("reset.done")}</Alert>
          <Link className="inline-block text-sm font-medium text-brand-strong hover:underline" to="/">{t("reset.goSignIn")}</Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.04em] sm:text-[34px]">{t("reset.title")}</h1>
          <p className="text-sm text-muted">{t("reset.hint")}</p>
        </div>
        <Field label={t("reset.newPassword")}>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus autoComplete="new-password" />
        </Field>
        <Field label={t("reset.confirm")} error={mismatch ? t("reset.mismatch") : null}>
          <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" invalid={mismatch} />
        </Field>
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">
          <li>{t("reset.ruleLength", { count: MIN_LENGTH })}</li>
          <li>{t("reset.ruleCommon")}</li>
          <li>{t("reset.ruleLogin")}</li>
        </ul>
        {reset.isError && (
          <Alert tone="bad">
            {reset.error.message}
            {reset.error instanceof ApiError && reset.error.status === 401 && <> <Link className="font-medium underline" to="/forgot-password">{t("reset.askNew")}</Link></>}
          </Alert>
        )}
        <Button type="submit" size="lg" loading={reset.isPending} disabled={!ready} className="w-full">{reset.isPending ? t("reset.working") : t("reset.submit")}</Button>
      </form>
    </AuthShell>
  );
}

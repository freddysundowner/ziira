import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Alert, Button, Field, Input, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { MIN_PASSWORD, passwordProblem, passwordReady } from "../helpers/password";

/**
 * Change your own password: the current one, then the new one twice. The server applies the rule (length, common
 * passwords, not your email) and ends your other sign-ins; this form only catches the obvious mistakes early.
 */
export function PasswordForm({ onDone, children }: { onDone: () => void; children?: React.ReactNode }) {
  const { t } = useTranslation("operator");
  const [form, setForm] = useState({ current: "", next: "", repeat: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const hint = passwordProblem(form);
  const save = useMutation({
    mutationFn: () => opUnwrap(opApi.POST("/api/v1/operator/password", { body: { current_password: form.current, new_password: form.next } })),
    meta: { silent: true },
    onSuccess: () => { setForm({ current: "", next: "", repeat: "" }); onDone(); },
    onError: (error: Error) => { setProblem(error.message); setForm((f) => ({ ...f, current: "" })); },
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!passwordReady(form) || save.isPending) return;
    setProblem(null);
    save.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("account.current")} required>
        <Input type="password" value={form.current} onChange={set("current")} autoComplete="current-password" autoFocus />
      </Field>
      <Field label={t("account.new")} hint={t("account.newHint", { min: MIN_PASSWORD })} error={hint === "short" || hint === "same" ? t(`account.${hint}`, { min: MIN_PASSWORD }) : null} required>
        <Input type="password" value={form.next} onChange={set("next")} autoComplete="new-password" />
      </Field>
      <Field label={t("account.repeat")} error={hint === "mismatch" ? t("account.mismatch") : null} required>
        <Input type="password" value={form.repeat} onChange={set("repeat")} autoComplete="new-password" />
      </Field>
      {problem && <Alert tone="bad">{problem}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={save.isPending} disabled={!passwordReady(form)}>{t("account.save")}</Button>
        {children}
      </div>
    </form>
  );
}

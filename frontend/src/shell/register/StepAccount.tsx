import { Alert, Button, Checkbox, Field, Input, useTranslation } from "@/sdk";

import type { FormApi } from "./form";
import type { ServerCheck } from "./PasswordMeter";
import { StepPassword } from "./StepPassword";
import { suggestEmail } from "./validators";

/** The last step: the email and password the owner signs in with, and the agreement. The email is checked for typos in well-known domains. */
export function StepAccount({ form, server, serverMessage, terms, privacy, serverError }: {
  form: FormApi; server: ServerCheck; serverMessage: string | null; terms: string; privacy: string; serverError: string | null;
}) {
  const { t } = useTranslation();
  const { values: v } = form;
  const suggestion = suggestEmail(v.email);
  return (
    <div className="space-y-6">
      <div className="max-w-xl space-y-2">
        <Field label={t("signup.field.email")} hint={t("signup.hint.email")} error={form.error("email")} required>
          <Input data-field="email" type="email" value={v.email} autoComplete="email" inputMode="email" maxLength={200}
            onChange={(e) => form.set("email", e.target.value)} onBlur={() => form.blur("email")} className="h-11 text-base" />
        </Field>
        {suggestion && (
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-warn" role="status">
            {t("signup.didYouMean", { email: suggestion })}
            <Button size="sm" variant="secondary" onClick={() => form.set("email", suggestion)}>{t("signup.useSuggestion")}</Button>
          </p>
        )}
      </div>
      <StepPassword form={form} server={server} serverMessage={serverMessage} />
      <div>
        <Checkbox
          checked={v.consent} onChange={(e) => { form.set("consent", e.target.checked); form.blur("consent"); }} aria-invalid={!!form.error("consent") || undefined}
          label={<span>{t("signup.consent.agree")} <a className="font-medium text-brand-strong underline" href={terms} target="_blank" rel="noreferrer">{t("signup.consent.terms")}</a> {t("signup.consent.and")} <a className="font-medium text-brand-strong underline" href={privacy} target="_blank" rel="noreferrer">{t("signup.consent.privacy")}</a>.</span>}
        />
        {form.error("consent") && <p role="alert" className="mt-1 text-xs text-bad">{form.error("consent")}</p>}
      </div>
      {serverError && <Alert tone="bad">{serverError}</Alert>}
    </div>
  );
}

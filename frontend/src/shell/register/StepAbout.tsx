import { Button, Field, Input, useTranslation } from "@/sdk";

import { ChoiceGroup } from "./ChoiceGroup";
import type { FormApi } from "./form";
import { ROLES } from "./state";
import { suggestEmail } from "./validators";

/** Step 2: who the person is. The email is checked for typos in well-known domains (a suggestion, never a refusal). */
export function StepAbout({ form }: { form: FormApi }) {
  const { t } = useTranslation();
  const { values: v } = form;
  const suggestion = suggestEmail(v.email);
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <Field label={t("signup.field.name")} hint={t("signup.hint.name")} error={form.error("name")} required>
        <Input data-field="name" value={v.name} autoComplete="name" maxLength={120} onChange={(e) => form.set("name", e.target.value)} onBlur={() => form.blur("name")} className="h-11 text-base" />
      </Field>
      <div className="space-y-2">
        <Field label={t("signup.field.email")} hint={t("signup.hint.email")} error={form.error("email")} required>
          <Input data-field="email" type="email" value={v.email} autoComplete="email" inputMode="email" maxLength={200} onChange={(e) => form.set("email", e.target.value)} onBlur={() => form.blur("email")} className="h-11 text-base" />
        </Field>
        {suggestion && (
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-warn" role="status">
            {t("signup.didYouMean", { email: suggestion })}
            <Button size="sm" variant="secondary" onClick={() => form.set("email", suggestion)}>{t("signup.useSuggestion")}</Button>
          </p>
        )}
      </div>
      <Field label={`${t("signup.field.phone")} (${t("signup.optional")})`} hint={t("signup.hint.phone")} error={form.error("phone")}>
        <Input data-field="phone" type="tel" value={v.phone} autoComplete="tel" inputMode="tel" maxLength={30} onChange={(e) => form.set("phone", e.target.value)} onBlur={() => form.blur("phone")} className="h-11 text-base" />
      </Field>
      <div className="space-y-1.5">
        <ChoiceGroup name="role" legend={`${t("signup.field.role")} (${t("signup.optional")})`} clearable value={v.role} onChange={(x) => form.set("role", x)}
          options={ROLES.map((r) => ({ value: r, label: t(`signup.role.${r}`) }))} />
        <p className="text-xs text-muted">{t("signup.hint.role")}</p>
      </div>
    </div>
  );
}

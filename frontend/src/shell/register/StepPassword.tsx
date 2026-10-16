import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { Field, IconButton, Input, useTranslation } from "@/sdk";

import type { FormApi } from "./form";
import { PasswordMeter, type ServerCheck } from "./PasswordMeter";
import { passwordRules } from "./validators";

/** Step 3: the password, with a live checklist (the server's own check says whether it is too common) and a confirmation. */
export function StepPassword({ form, server, serverMessage }: { form: FormApi; server: ServerCheck; serverMessage: string | null }) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  const { values: v } = form;
  const type = show ? "text" : "password";
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-5">
        <Field label={t("signup.field.password")} error={form.error("password")} required>
          <div className="relative">
            <Input data-field="password" type={type} value={v.password} autoComplete="new-password" maxLength={200} className="h-11 pr-11 text-base"
              onChange={(e) => form.set("password", e.target.value)} onBlur={() => form.blur("password")} />
            <IconButton label={show ? t("signup.hidePassword") : t("signup.showPassword")} aria-pressed={show} className="absolute right-0 top-0 h-11" onClick={() => setShow(!show)}>
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </IconButton>
          </div>
        </Field>
        <Field label={t("signup.field.confirm")} error={form.error("confirm")} required>
          <Input data-field="confirm" type={type} value={v.confirm} autoComplete="new-password" maxLength={200} className="h-11 text-base"
            onChange={(e) => form.set("confirm", e.target.value)} onBlur={() => form.blur("confirm")} />
        </Field>
      </div>
      <PasswordMeter password={v.password} rules={passwordRules(v.password, v.email)} server={server} serverMessage={serverMessage}
        matches={v.confirm ? v.password === v.confirm : null} />
    </div>
  );
}

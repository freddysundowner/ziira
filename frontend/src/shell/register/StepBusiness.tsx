import { Combobox, Field, Input, useTranslation } from "@/sdk";

import type { Country } from "../countries";
import { ChoiceGroup } from "./ChoiceGroup";
import type { FormApi } from "./form";
import { KINDS } from "./state";

export interface Industry { id: string; title: string; summary: string }

/** Whether to ask what kind of service business this is: only for the Services edition, and only when packs are installed. */
export const asksIndustry = (edition: string, industries: readonly Industry[]) => edition === "services" && industries.length > 0;

/** Every time zone this browser knows (reference data from the platform, not a list of ours), with the country's own first. */
export function timeZones(own: string): string[] {
  let all: string[] = [];
  try { all = Intl.supportedValuesOf("timeZone"); } catch { /* an older browser: only the country's own */ }
  return [...new Set([own, ...all].filter(Boolean))];
}

/** Step 4: the business. Currency, time zone and phone calling code come from the country and are changed later in Settings. */
export function StepBusiness({ form, countries, country, onCountry, industries = [] }: {
  form: FormApi; countries: readonly Country[]; currencies?: readonly string[]; country: Country | undefined; onCountry: (code: string) => void;
  /** The kinds of service business on offer (the installed industry packs), asked only with the Services edition. */
  industries?: readonly Industry[];
}) {
  const { t } = useTranslation();
  const { values: v } = form;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("signup.field.business")} hint={t("signup.hint.business")} error={form.error("business")} required>
          <Input data-field="business" value={v.business} autoComplete="organization" maxLength={120} className="h-11 text-base"
            onChange={(e) => form.set("business", e.target.value)} onBlur={() => form.blur("business")} />
        </Field>
        <Field label={t("signup.field.country")} hint={t("signup.hint.countrySearch")} error={form.error("country")} required>
          <Combobox value={v.country} placeholder={t("signup.choose")} invalid={!!form.error("country")}
            options={countries.map((c) => ({ value: c.code, label: c.name }))}
            onChange={(code) => { onCountry(code); form.blur("country"); }} />
        </Field>
      </div>
      {country?.pack && <p className="text-sm text-muted">{t("register.packNote", { country: country.name })}</p>}
      <div className="grid gap-4">
        {asksIndustry(v.edition, industries) ? (
          <div className="space-y-1.5 lg:col-span-1">
            <ChoiceGroup name="kind" legend={`${t("signup.field.industry")} (${t("signup.optional")})`} clearable value={v.kind} onChange={(x) => form.set("kind", x)}
              options={[...industries.map((i) => ({ value: i.id, label: i.title })), { value: "other", label: t("signup.kind.other") }]} />
            {industries.find((i) => i.id === v.kind)?.summary && <p className="text-xs text-muted">{industries.find((i) => i.id === v.kind)?.summary}</p>}
          </div>
        ) : (
          // the usual four kinds, plus the packs recommended for this edition (a pharmacy for the shop editions)
          <ChoiceGroup name="kind" legend={`${t("signup.field.kind")} (${t("signup.optional")})`} clearable value={v.kind} onChange={(x) => form.set("kind", x)}
            options={[...KINDS.map((x) => ({ value: x, label: t(`signup.kind.${x}`) })), ...industries.map((i) => ({ value: i.id, label: i.title }))]} />
        )}
      </div>
    </div>
  );
}

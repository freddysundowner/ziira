import { Combobox, Field, Input, Select, useTranslation } from "@/sdk";

import type { Country } from "../countries";
import { ChoiceGroup } from "./ChoiceGroup";
import type { FormApi } from "./form";
import { BRANCH_SIZES, KINDS, STAFF_SIZES } from "./state";

export interface Industry { id: string; title: string; summary: string }

/** Whether to ask what kind of service business this is: only for the Services edition, and only when packs are installed. */
export const asksIndustry = (edition: string, industries: readonly Industry[]) => edition === "services" && industries.length > 0;

/** Every time zone this browser knows (reference data from the platform, not a list of ours), with the country's own first. */
export function timeZones(own: string): string[] {
  let all: string[] = [];
  try { all = Intl.supportedValuesOf("timeZone"); } catch { /* an older browser: only the country's own */ }
  return [...new Set([own, ...all].filter(Boolean))];
}

/** Step 4: the business. Choosing a country fills in currency, time zone and calling code (all still changeable). */
export function StepBusiness({ form, countries, currencies, country, onCountry, industries = [] }: {
  form: FormApi; countries: readonly Country[]; currencies: readonly string[]; country: Country | undefined; onCountry: (code: string) => void;
  /** The kinds of service business on offer (the installed industry packs), asked only with the Services edition. */
  industries?: readonly Industry[];
}) {
  const { t } = useTranslation();
  const { values: v } = form;
  const zones = timeZones(v.zone);
  const currencyList = v.currency && !currencies.includes(v.currency) ? [v.currency, ...currencies] : currencies;
  const taxLabel = country?.taxIdLabel || t("register.taxIdDefault");
  return (
    <div className="space-y-6">
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label={t("signup.field.business")} hint={t("signup.hint.business")} error={form.error("business")} required>
          <Input data-field="business" value={v.business} autoComplete="organization" maxLength={120} className="h-11 text-base"
            onChange={(e) => form.set("business", e.target.value)} onBlur={() => form.blur("business")} />
        </Field>
        <Field label={t("signup.field.country")} hint={t("signup.hint.countrySearch")} error={form.error("country")} required>
          <Combobox value={v.country} placeholder={t("signup.choose")} invalid={!!form.error("country")}
            options={countries.map((c) => ({ value: c.code, label: c.name }))}
            onChange={(code) => { onCountry(code); form.blur("country"); }} />
        </Field>
        <Field label={t("signup.field.currency")} hint={t("signup.hint.currency")} error={form.error("currency")} required>
          <Select data-field="currency" value={v.currency} disabled={!v.country} className="h-11 text-base" onChange={(e) => form.set("currency", e.target.value)} onBlur={() => form.blur("currency")}>
            {!v.currency && <option value="" disabled />}
            {currencyList.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label={t("signup.field.zone")} hint={t("signup.hint.zone")} error={form.error("zone")}>
          <Select data-field="zone" value={v.zone} disabled={!v.country} className="h-11 text-base" onChange={(e) => form.set("zone", e.target.value)}>
            {zones.map((z) => <option key={z} value={z}>{z}</option>)}
          </Select>
        </Field>
        <Field label={t("signup.field.calling")} hint={t("signup.hint.calling")} error={form.error("calling")}>
          <div className="flex items-center gap-2">
            <span aria-hidden className="text-base text-muted">+</span>
            <Input data-field="calling" inputMode="numeric" value={v.calling} maxLength={4} className="h-11 text-base" onChange={(e) => form.set("calling", e.target.value.replace(/\D/g, ""))} onBlur={() => form.blur("calling")} />
          </div>
        </Field>
        <Field label={`${t("signup.field.tax", { label: taxLabel })} (${t("signup.optional")})`} hint={country?.taxIdPattern ? t("signup.hint.taxPattern", { pattern: country.taxIdPattern }) : t("signup.hint.tax")} error={form.error("tax")}>
          <Input data-field="tax" value={v.tax} autoComplete="off" maxLength={30} className="h-11 text-base" onChange={(e) => form.set("tax", e.target.value)} onBlur={() => form.blur("tax")} />
        </Field>
      </div>
      {country?.pack && <p className="text-sm text-muted">{t("register.packNote", { country: country.name })}</p>}
      <div className="grid gap-5 lg:grid-cols-3">
        <ChoiceGroup name="branches" legend={`${t("signup.field.branches")} (${t("signup.optional")})`} clearable value={v.branches} onChange={(x) => form.set("branches", x)} options={BRANCH_SIZES.map((x) => ({ value: x, label: t(`signup.branches.${x}`) }))} />
        <ChoiceGroup name="staff" legend={`${t("signup.field.staff")} (${t("signup.optional")})`} clearable value={v.staff} onChange={(x) => form.set("staff", x)} options={STAFF_SIZES.map((x) => ({ value: x, label: t(`signup.staff.${x}`) }))} />
        {asksIndustry(v.edition, industries) ? (
          <div className="space-y-1.5 lg:col-span-1">
            <ChoiceGroup name="kind" legend={`${t("signup.field.industry")} (${t("signup.optional")})`} clearable value={v.kind} onChange={(x) => form.set("kind", x)}
              options={[...industries.map((i) => ({ value: i.id, label: i.title })), { value: "other", label: t("signup.kind.other") }]} />
            {industries.find((i) => i.id === v.kind)?.summary && <p className="text-xs text-muted">{industries.find((i) => i.id === v.kind)?.summary}</p>}
          </div>
        ) : (
          <ChoiceGroup name="kind" legend={`${t("signup.field.kind")} (${t("signup.optional")})`} clearable value={v.kind} onChange={(x) => form.set("kind", x)} options={KINDS.map((x) => ({ value: x, label: t(`signup.kind.${x}`) }))} />
        )}
      </div>
    </div>
  );
}

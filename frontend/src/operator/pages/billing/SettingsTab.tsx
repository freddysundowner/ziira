import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Alert, Button, Card, ErrorState, Field, FormGrid, Input, Select, Skeleton, Textarea, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usePlans } from "../../catalog";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import {
  dunningFromDraft, dunningToDraft, type DunningDraft, numberValue, taxLinesFromDraft, taxLinesToDraft, type TaxLineDraft, VENDOR_FIELDS, vendorToDraft, type VendorDraft,
} from "../../helpers/settings";
import { useOperatorCan } from "../../me";
import { SettingCard } from "./SettingCard";
import { useRefreshOperator } from "./invoiceDialogs";

export default function SettingsTab() {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.billing");
  const settings = useQuery({ queryKey: ["operator", "settings"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/platform-settings")) });
  const plans = usePlans();

  if (settings.isPending) return <div className="space-y-3"><Skeleton className="h-40 w-full" /><Skeleton className="h-40 w-full" /></div>;
  if (settings.isError) return <ErrorState title={t("billing.settings.loadFailed")} message={settings.error.message} onRetry={() => void settings.refetch()} />;
  const v = settings.data.values;
  const k = (key: string) => JSON.stringify(v[key]);
  const common = { editable };

  return (
    <div className="space-y-6">
      {!editable && <Alert tone="info">{t("billing.settings.readOnly")}</Alert>}
      {editable && <RunBilling />}

      <Section title={t("billing.settings.sections.invoices")}>
        <SettingCard<VendorDraft> key={k("vendor")} settingKey="vendor" title={t("billing.settings.vendor")} hint={t("billing.settings.vendorHint")} stored={v.vendor} toDraft={(s) => vendorToDraft(s as Record<string, unknown>)} fromDraft={(d) => d} {...common}>
          {(d, set) => (
            <FormGrid>
              {VENDOR_FIELDS.map((f) => (
                <Field key={f} label={t(`billing.settings.vendorFields.${f}`)} className={f === "address" ? "sm:col-span-2" : undefined}>
                  <Input value={d[f]} onChange={(e) => set({ ...d, [f]: e.target.value })} maxLength={300} />
                </Field>
              ))}
            </FormGrid>
          )}
        </SettingCard>

        <SettingCard<TaxLineDraft[]> key={k("billing.tax_lines")} settingKey="billing.tax_lines" title={t("billing.settings.taxLines")} hint={t("billing.settings.taxLinesHint")} stored={v["billing.tax_lines"]} toDraft={taxLinesToDraft} fromDraft={taxLinesFromDraft} {...common}>
          {(lines, set) => (
            <>
              {lines.length === 0 && <p className="text-sm text-muted">{t("billing.settings.noTaxLines")}</p>}
              {lines.map((line, i) => (
                <div key={i} className="grid grid-cols-[1fr_6rem_auto] items-end gap-2">
                  <Field label={t("billing.settings.taxName")}><Input value={line.name} maxLength={60} onChange={(e) => set(lines.map((l, n) => (n === i ? { ...l, name: e.target.value } : l)))} /></Field>
                  <Field label={t("billing.settings.taxRate")}><Input value={line.rate_percent} inputMode="decimal" className="tnum text-right" onChange={(e) => set(lines.map((l, n) => (n === i ? { ...l, rate_percent: e.target.value } : l)))} /></Field>
                  <Button variant="ghost" size="sm" aria-label={t("billing.settings.removeTax")} onClick={() => set(lines.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></Button>
                </div>
              ))}
              {lines.length < 5 && <Button size="sm" variant="secondary" onClick={() => set([...lines, { name: "", rate_percent: "" }])}><Plus className="h-4 w-4" /> {t("billing.settings.addTax")}</Button>}
            </>
          )}
        </SettingCard>

        <SettingCard<string> key={k("billing.payment_instructions")} settingKey="billing.payment_instructions" title={t("billing.settings.paymentInstructions")} hint={t("billing.settings.paymentInstructionsHint")} stored={v["billing.payment_instructions"]} toDraft={String} fromDraft={(d) => d} {...common}>
          {(d, set) => <Field label={t("billing.settings.paymentInstructions")}><Textarea value={d} onChange={(e) => set(e.target.value)} rows={4} maxLength={2000} /></Field>}
        </SettingCard>

        <div className="grid gap-4 md:grid-cols-3">
          <SettingCard<string> key={k("billing.invoice_prefix")} settingKey="billing.invoice_prefix" title={t("billing.settings.prefix")} hint={t("billing.settings.prefixHint")} stored={v["billing.invoice_prefix"]} toDraft={String} fromDraft={(d) => d} {...common}>
            {(d, set) => <Field label={t("billing.settings.prefix")}><Input value={d} onChange={(e) => set(e.target.value)} maxLength={12} className="font-mono" /></Field>}
          </SettingCard>
          <DaysCard settingKey="billing.due_days" title={t("billing.settings.dueDays")} hint={t("billing.settings.dueDaysHint")} stored={v["billing.due_days"]} editable={editable} />
          <DaysCard settingKey="billing.renewal_lead_days" title={t("billing.settings.renewalLead")} hint={t("billing.settings.renewalLeadHint")} stored={v["billing.renewal_lead_days"]} editable={editable} />
        </div>
      </Section>

      <Section title={t("billing.settings.sections.dunning")}>
        <SettingCard<DunningDraft> key={k("billing.dunning")} settingKey="billing.dunning" title={t("billing.settings.dunning")} hint={t("billing.settings.dunningHint")} stored={v["billing.dunning"]} toDraft={(s) => dunningToDraft(s as Record<string, unknown>)} fromDraft={dunningFromDraft} {...common}>
          {(d, set) => (
            <>
              <Field label={t("billing.settings.reminders")} hint={t("billing.settings.remindersHint")}><Input value={d.reminders} onChange={(e) => set({ ...d, reminders: e.target.value })} className="font-mono" /></Field>
              <FormGrid>
                {(["past_due_after_days", "grace_after_days", "suspend_after_days", "expire_after_days"] as const).map((f) => (
                  <Field key={f} label={t(`billing.settings.dunningSteps.${f}`)}><Input value={d[f]} inputMode="numeric" className="tnum" onChange={(e) => set({ ...d, [f]: e.target.value })} /></Field>
                ))}
              </FormGrid>
            </>
          )}
        </SettingCard>
        <SettingCard<string> key={k("billing.notify_emails")} settingKey="billing.notify_emails" title={t("billing.settings.notifyEmails")} hint={t("billing.settings.notifyEmailsHint")} stored={v["billing.notify_emails"]} toDraft={String} fromDraft={(d) => d} {...common}>
          {(d, set) => <Field label={t("billing.settings.notifyEmails")}><Input value={d} onChange={(e) => set(e.target.value)} maxLength={500} /></Field>}
        </SettingCard>
      </Section>

      <Section title={t("billing.settings.sections.plans")}>
        <div className="grid gap-4 md:grid-cols-2">
          <SettingCard<string> key={k("billing.proration")} settingKey="billing.proration" title={t("billing.settings.proration")} hint={t("billing.settings.prorationHint")} stored={v["billing.proration"]}
            toDraft={(s) => String((s as { downgrade?: string })?.downgrade ?? "period_end")} fromDraft={(d) => ({ downgrade: d })} {...common}>
            {(d, set) => (
              <Field label={t("billing.settings.downgrade")}>
                <Select value={d} onChange={(e) => set(e.target.value)}>
                  <option value="period_end">{t("billing.settings.atPeriodEnd")}</option>
                  <option value="now">{t("billing.settings.immediately")}</option>
                </Select>
              </Field>
            )}
          </SettingCard>
          <SettingCard<string> key={k("billing.default_plan_code")} settingKey="billing.default_plan_code" title={t("billing.settings.defaultPlan")} hint={t("billing.settings.defaultPlanHint")} stored={v["billing.default_plan_code"]} toDraft={String} fromDraft={(d) => d} {...common}>
            {(d, set) => (
              <Field label={t("billing.settings.defaultPlan")}>
                <Select value={d} onChange={(e) => set(e.target.value)}>
                  <option value="">{t("billing.settings.noDefaultPlan")}</option>
                  {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                  {d && !(plans.data ?? []).some((p) => p.code === d) && <option value={d}>{d}</option>}
                </Select>
              </Field>
            )}
          </SettingCard>
        </div>
      </Section>

      <Section title={t("billing.settings.sections.data")}>
        <div className="grid gap-4 md:grid-cols-2">
          <DaysCard settingKey="billing.retention_days" title={t("billing.settings.retention")} hint={t("billing.settings.retentionHint")} stored={v["billing.retention_days"]} editable={editable} />
          <DaysCard settingKey="billing.cooling_off_days" title={t("billing.settings.coolingOff")} hint={t("billing.settings.coolingOffHint")} stored={v["billing.cooling_off_days"]} editable={editable} />
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="space-y-4"><h2 className="text-base font-semibold">{title}</h2>{children}</section>;
}

/** A setting that is a number of days. */
function DaysCard({ settingKey, title, hint, stored, editable }: { settingKey: string; title: string; hint: string; stored: unknown; editable: boolean }) {
  const { t } = useTranslation("operator");
  return (
    <SettingCard<string> key={JSON.stringify(stored)} settingKey={settingKey} title={title} hint={hint} stored={stored} toDraft={String} fromDraft={numberValue} editable={editable}>
      {(d, set) => <Field label={t("billing.settings.days")}><Input value={d} inputMode="numeric" className="tnum" onChange={(e) => set(e.target.value)} /></Field>}
    </SettingCard>
  );
}

/** Runs the recurring billing pass now (the worker does it hourly) and shows what it did. */
function RunBilling() {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<{ invoices: number; cancelled: number; reminders: number; moved: number; deletions: number } | null>(null);
  return (
    <Card title={t("billing.run.title")} description={t("billing.run.hint")} actions={<Button variant="secondary" onClick={() => setConfirming(true)}>{t("billing.run.button")}</Button>}>
      {result ? (
        <ul className="grid gap-2 text-sm sm:grid-cols-5" aria-label={t("billing.run.result")}>
          {(["invoices", "cancelled", "reminders", "moved", "deletions"] as const).map((key) => (
            <li key={key} className="rounded-lg border border-line p-2"><p className="tnum text-lg font-semibold">{result[key]}</p><p className="text-xs text-muted">{t(`billing.run.counts.${key}`)}</p></li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">{t("billing.run.notYet")}</p>}
      {confirming && (
        <ChangeConfirm title={t("billing.run.title")} message={<p>{t("billing.run.confirm")}</p>} confirmLabel={t("billing.run.button")}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/billing/run"))}
          onDone={(r) => { setResult(r); refresh(); }} onClose={() => setConfirming(false)} />
      )}
    </Card>
  );
}

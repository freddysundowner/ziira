import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api, Button, Card, ErrorState, Field, FormGrid, Input, NumberInput, PageHeader, Select, Skeleton, Switch, Tabs, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { PracticeData } from "../components/PracticeData";
import { ServiceItemPicker } from "../components/ServiceItemPicker";
import { useSettings, useWorkCompany } from "../hooks";
import { formatClock, parseDuration } from "../lib";
import { GROUPINGS, type Settings } from "../types";

const STEPS = [1, 5, 6, 10, 15, 30, 60] as const;
const TIMER_ROUNDING = [0, 1, 5, 6, 10, 15, 30, 60] as const;
const INVOICE_ROUNDING = [0, 5, 6, 10, 15, 30, 60] as const;

function Toggle({ label, hint, checked, onChange }: { label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div><p className="text-sm font-medium">{label}</p><p className="text-xs text-muted">{hint}</p></div>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

const Section = ({ title, children }: { title: string; children: ReactNode }) => <Card title={title}><div className="space-y-4">{children}</div></Card>;

/** Time and billing settings of the business, each explained in a sentence. */
export default function SettingsPage() {
  const { t } = useTranslation("timebilling");
  const { companyId, companies, setCompanyId } = useWorkCompany();
  const settings = useSettings(companyId);
  const qc = useQueryClient();
  const f = useFormState({
    step: "1", timerStep: "0", timerMode: "nearest", weekStart: "1", capacity: "", invoiceRound: "0", group: "project", alert: "80", unsubmitted: "2", unbilled: "30", retention: "",
    partnerAbove: "0", markup: "0", receipt: "", nudge: "", nudgeHour: "9", remind: "2", escalate: "5",
  });
  const [tab, setTab] = useState<"settings" | "templates" | "activities" | "wording">("settings");
  const [days, setDays] = useState<number[]>([1, 2, 3, 4, 5]);
  const [flags, setFlags] = useState({ approval: true, tax: false, partner: false });
  const [items, setItems] = useState({ service: "", expense: "" });
  const { reset, set } = f;

  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    reset();
    set("step", String(s.minute_step)); set("timerStep", String(s.timer_round_minutes)); set("timerMode", s.timer_round_mode); set("weekStart", String(s.week_starts_on));
    set("capacity", formatClock(s.capacity_minutes_week)); set("invoiceRound", String(s.invoice_round_minutes)); set("group", s.default_group_by); set("alert", String(s.budget_alert_percent));
    set("unsubmitted", String(s.unsubmitted_after_days)); set("unbilled", String(s.unbilled_after_days)); set("retention", s.notes_retention_days === null ? "" : String(s.notes_retention_days));
    set("partnerAbove", s.partner_review_above); set("markup", s.default_markup_percent); set("receipt", s.receipt_required_above ?? "");
    set("nudge", s.nudge_minutes ? formatClock(s.nudge_minutes) : ""); set("nudgeHour", String(s.nudge_hour)); set("remind", String(s.approval_reminder_days)); set("escalate", String(s.approval_escalate_days));
    setDays(s.work_days);
    setFlags({ approval: s.approval_required, tax: s.rates_include_tax, partner: s.partner_review });
    setItems({ service: s.service_product_id ?? "", expense: s.expense_product_id ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.data]);

  const capacity = parseDuration(f.values.capacity, 10080);
  const nudge = parseDuration(f.values.nudge, 1440);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      return unwrap(api.PUT("/api/v1/timebilling/settings", { body: {
        company_id: companyId, minute_step: Number(v.step) as 1, timer_round_minutes: Number(v.timerStep) as 0, timer_round_mode: v.timerMode as "up", week_starts_on: Number(v.weekStart),
        capacity_minutes_week: capacity ?? 0, approval_required: flags.approval, rates_include_tax: flags.tax, service_product_id: items.service || null, expense_product_id: items.expense || null,
        invoice_round_minutes: Number(v.invoiceRound) as 0, default_group_by: v.group as "project", budget_alert_percent: Number(v.alert) || 80,
        unsubmitted_after_days: Number(v.unsubmitted) || 0, unbilled_after_days: Number(v.unbilled) || 1, notes_retention_days: v.retention === "" ? null : Number(v.retention),
        partner_review: flags.partner, partner_review_above: v.partnerAbove || "0", default_markup_percent: v.markup || "0", receipt_required_above: v.receipt === "" ? null : v.receipt,
        nudge_minutes: nudge ?? 0, nudge_hour: Number(v.nudgeHour) || 0, work_days: days.length ? days : [1, 2, 3, 4, 5], approval_reminder_days: Number(v.remind) || 0, approval_escalate_days: Number(v.escalate) || 0 } }));
    },
    onSuccess: (s: Settings) => { qc.setQueryData(["timebilling", "settings", companyId], s); toast(t("settings.saved"), "ok"); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const minutes = (m: number) => t("settings.minutesValue", { count: m });

  return (
    <>
      <PageHeader title={t("settings.title")} description={t("settings.hint")} actions={<CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />} />
      <Tabs tabs={[{ id: "settings", label: t("settings.tabSettings") }, { id: "templates", label: t("practice.tabTemplates") }, { id: "activities", label: t("practice.tabActivities") }, { id: "wording", label: t("practice.tabWording") }]} value={tab} onChange={setTab} />
      {tab !== "settings" && <PracticeData companyId={companyId} part={tab} />}
      {tab === "settings" && settings.isLoading && <Skeleton className="h-64 w-full" />}
      {tab === "settings" && settings.error && <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />}
      {tab === "settings" && settings.data && (
        <form onSubmit={submit} className="space-y-4">
          <Section title={t("settings.entering")}>
            <FormGrid>
              <Field label={t("settings.minuteStep")} hint={t("settings.minuteStepHint")} error={f.error("minute_step")}>
                <Select {...f.bind("step")}>{STEPS.map((m) => <option key={m} value={m}>{minutes(m)}</option>)}</Select>
              </Field>
              <Field label={t("settings.weekStart")} hint={t("settings.weekStartHint")} error={f.error("week_starts_on")}>
                <Select {...f.bind("weekStart")}>{[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{t(`weekdays.${d}`)}</option>)}</Select>
              </Field>
              <Field label={t("settings.timerRound")} hint={t("settings.timerRoundHint")} error={f.error("timer_round_minutes")}>
                <Select {...f.bind("timerStep")}>{TIMER_ROUNDING.map((m) => <option key={m} value={m}>{m === 0 ? t("settings.noRounding") : minutes(m)}</option>)}</Select>
              </Field>
              <Field label={t("settings.timerMode")} hint={t("settings.timerModeHint")} error={f.error("timer_round_mode")}>
                <Select {...f.bind("timerMode")} disabled={f.values.timerStep === "0"}>{(["up", "nearest", "down"] as const).map((m) => <option key={m} value={m}>{t(`settings.mode.${m}`)}</option>)}</Select>
              </Field>
              <Field label={t("settings.capacity")} hint={t("settings.capacityHint")} error={f.error("capacity_minutes_week") ?? (capacity === null ? t("timeInvalid") : null)}><Input {...f.bind("capacity")} placeholder="40:00" /></Field>
            </FormGrid>
          </Section>
          <Section title={t("settings.approval")}>
            <Toggle label={t("settings.approvalRequired")} hint={t("settings.approvalRequiredHint")} checked={flags.approval} onChange={(v) => setFlags((x) => ({ ...x, approval: v }))} />
          </Section>
          <Section title={t("settings.review")}>
            <Toggle label={t("settings.partnerReview")} hint={t("settings.partnerReviewHint")} checked={flags.partner} onChange={(v) => setFlags((x) => ({ ...x, partner: v }))} />
            {flags.partner && <Field label={t("settings.partnerAbove")} hint={t("settings.partnerAboveHint")} error={f.error("partner_review_above")}><NumberInput value={f.values.partnerAbove} onChange={(v) => f.set("partnerAbove", v)} /></Field>}
            <FormGrid>
              <Field label={t("settings.remind")} hint={t("settings.remindHint")} error={f.error("approval_reminder_days")}><NumberInput value={f.values.remind} onChange={(v) => f.set("remind", v.replace(/\./g, ""))} /></Field>
              <Field label={t("settings.escalate")} hint={t("settings.escalateHint")} error={f.error("approval_escalate_days")}><NumberInput value={f.values.escalate} onChange={(v) => f.set("escalate", v.replace(/\./g, ""))} /></Field>
            </FormGrid>
          </Section>
          <Section title={t("settings.disbursements")}>
            <FormGrid>
              <Field label={t("settings.markup")} hint={t("settings.markupHint")} error={f.error("default_markup_percent")}><NumberInput value={f.values.markup} onChange={(v) => f.set("markup", v)} /></Field>
              <Field label={t("settings.receipt")} hint={t("settings.receiptHint")} error={f.error("receipt_required_above")}><NumberInput value={f.values.receipt} onChange={(v) => f.set("receipt", v)} placeholder="—" /></Field>
            </FormGrid>
          </Section>
          <Section title={t("settings.nudges")}>
            <p className="text-sm text-muted">{t("settings.nudgesHint")}</p>
            <FormGrid>
              <Field label={t("settings.nudgeMinutes")} hint={t("settings.nudgeMinutesHint")} error={f.error("nudge_minutes") ?? (f.values.nudge !== "" && nudge === null ? t("timeInvalid") : null)}><Input {...f.bind("nudge")} placeholder="6:00" /></Field>
              <Field label={t("settings.nudgeHour")} hint={t("settings.nudgeHourHint")} error={f.error("nudge_hour")}><Select {...f.bind("nudgeHour")}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${String(h).padStart(2, "0")}:00`}</option>)}</Select></Field>
            </FormGrid>
            <fieldset><legend className="mb-1 text-sm font-medium">{t("settings.workDays")}</legend>
              <div className="flex flex-wrap gap-3">{[1, 2, 3, 4, 5, 6, 7].map((d) => <label key={d} className="flex items-center gap-1.5 text-sm"><input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={days.includes(d)} onChange={(e) => setDays((x) => (e.target.checked ? [...x, d].sort() : x.filter((y) => y !== d)))} />{t(`weekdays.${d}`)}</label>)}</div>
            </fieldset>
          </Section>
          <Section title={t("settings.billing")}>
            <Toggle label={t("settings.ratesIncludeTax")} hint={t("settings.ratesIncludeTaxHint")} checked={flags.tax} onChange={(v) => setFlags((x) => ({ ...x, tax: v }))} />
            <FormGrid>
              <Field label={t("settings.serviceItem")} hint={t("settings.serviceItemHint")} error={f.error("service_product_id")}><ServiceItemPicker value={items.service} onChange={(v) => setItems((x) => ({ ...x, service: v }))} /></Field>
              <Field label={t("settings.expenseItem")} hint={t("settings.expenseItemHint")} error={f.error("expense_product_id")}><ServiceItemPicker value={items.expense} onChange={(v) => setItems((x) => ({ ...x, expense: v }))} /></Field>
              <Field label={t("settings.invoiceRound")} hint={t("settings.invoiceRoundHint")} error={f.error("invoice_round_minutes")}>
                <Select {...f.bind("invoiceRound")}>{INVOICE_ROUNDING.map((m) => <option key={m} value={m}>{m === 0 ? t("settings.noRounding") : minutes(m)}</option>)}</Select>
              </Field>
              <Field label={t("settings.group")} hint={t("settings.groupHint")} error={f.error("default_group_by")}>
                <Select {...f.bind("group")}>{GROUPINGS.map((g) => <option key={g} value={g}>{t(`grouping.${g}`)}</option>)}</Select>
              </Field>
            </FormGrid>
          </Section>
          <Section title={t("settings.warnings")}>
            <FormGrid cols={2}>
              <Field label={t("settings.budgetAlert")} hint={t("settings.budgetAlertHint")} error={f.error("budget_alert_percent")}><NumberInput value={f.values.alert} onChange={(v) => f.set("alert", v.replace(/\./g, ""))} /></Field>
              <Field label={t("settings.unsubmitted")} hint={t("settings.unsubmittedHint")} error={f.error("unsubmitted_after_days")}><NumberInput value={f.values.unsubmitted} onChange={(v) => f.set("unsubmitted", v.replace(/\./g, ""))} /></Field>
              <Field label={t("settings.unbilled")} hint={t("settings.unbilledHint")} error={f.error("unbilled_after_days")}><NumberInput value={f.values.unbilled} onChange={(v) => f.set("unbilled", v.replace(/\./g, ""))} /></Field>
              <Field label={t("settings.retention")} hint={t("settings.retentionHint")} error={f.error("notes_retention_days")}><NumberInput value={f.values.retention} onChange={(v) => f.set("retention", v.replace(/\./g, ""))} placeholder="—" /></Field>
            </FormGrid>
          </Section>
          <div className="flex justify-end"><Button type="submit" loading={save.isPending} disabled={capacity === null}>{t("save")}</Button></div>
        </form>
      )}
    </>
  );
}

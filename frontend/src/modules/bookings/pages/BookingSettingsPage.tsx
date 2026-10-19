import { useEffect, useState } from "react";

import {
  Alert, api, Button, Card, Checkbox, ErrorState, Field, FormGrid, Input, NumberInput, PageHeader, Select, SkeletonRows, Textarea, toast, unwrap, useCan, useMutation, useQuery,
  useTranslation,
} from "@/sdk";

import { ShareLink } from "../components/ShareLink";
import { useBranch, useRefreshBookings } from "../hooks";
import type { Settings } from "../types";

interface Draft {
  online_enabled: boolean; slug: string; auto_confirm: boolean; show_resources_publicly: boolean; public_name: string; public_note: string; consent_text: string;
  min_notice_minutes: string; max_days_ahead: string; slot_granularity_minutes: string; default_buffer_minutes: string; cancel_window_hours: string;
  reminders_enabled: boolean; reminder_hours_before: string; quiet_start: string; quiet_end: string; invoice_on_completion: boolean; invoice_due_days: string;
  late_cancel_fee_percent: string; no_show_fee_percent: string; fee_product_id: string; waitlist_confirm_minutes: string; rebook_prompt_hours: string;
  recalls_enabled: boolean; deposit_note: string; patch_test_valid_days: string; commission_excludes_tax: boolean; discount_limit_percent: string;
  reminder_template: string; recall_template: string; rebook_template: string;
}

const draftOf = (s: Settings): Draft => ({
  online_enabled: s.online_enabled, slug: s.slug ?? "", auto_confirm: s.auto_confirm, show_resources_publicly: s.show_resources_publicly,
  public_name: s.public_name ?? "", public_note: s.public_note ?? "", consent_text: s.consent_text ?? "",
  min_notice_minutes: String(s.min_notice_minutes), max_days_ahead: String(s.max_days_ahead), slot_granularity_minutes: String(s.slot_granularity_minutes),
  default_buffer_minutes: String(s.default_buffer_minutes), cancel_window_hours: String(s.cancel_window_hours), reminders_enabled: s.reminders_enabled,
  reminder_hours_before: String(s.reminder_hours_before), quiet_start: s.quiet_start.slice(0, 5), quiet_end: s.quiet_end.slice(0, 5),
  invoice_on_completion: s.invoice_on_completion, invoice_due_days: s.invoice_due_days == null ? "" : String(s.invoice_due_days),
  late_cancel_fee_percent: s.late_cancel_fee_percent, no_show_fee_percent: s.no_show_fee_percent, fee_product_id: s.fee_product_id ?? "",
  waitlist_confirm_minutes: String(s.waitlist_confirm_minutes), rebook_prompt_hours: String(s.rebook_prompt_hours), recalls_enabled: s.recalls_enabled,
  deposit_note: s.deposit_note ?? "", patch_test_valid_days: s.patch_test_valid_days == null ? "" : String(s.patch_test_valid_days),
  commission_excludes_tax: s.commission_excludes_tax, discount_limit_percent: s.discount_limit_percent ?? "",
  reminder_template: s.reminder_template ?? "", recall_template: s.recall_template ?? "", rebook_template: s.rebook_template ?? "",
});

const TEMPLATES = {
  reminder_template: ["appointment_reminder", "appointment_reminder_clinic"],
  recall_template: ["appointment_recall", "appointment_recall_clinic"],
  rebook_template: ["appointment_rebook", "appointment_rebook_clinic"],
} as const;

export default function BookingSettingsPage() {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const refresh = useRefreshBookings();
  const { companyId } = useBranch();
  const query = useQuery({
    queryKey: ["bookings", "settings", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/settings", { params: { query: { company_id: companyId } } })),
  });
  const [d, setD] = useState<Draft | null>(null);
  useEffect(() => { if (query.data) setD(draftOf(query.data)); }, [query.data]);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setD((x) => (x ? { ...x, [key]: value } : x));
  const int = (v: string) => Number(v) || 0;

  const save = useMutation({
    mutationFn: () => {
      const x = d as Draft;
      return unwrap(api.PATCH("/api/v1/bookings/settings", { params: { query: { company_id: companyId } }, body: {
        slug: x.slug.trim().toLowerCase(), online_enabled: x.online_enabled, auto_confirm: x.auto_confirm, show_resources_publicly: x.show_resources_publicly,
        public_name: x.public_name.trim() || null, public_note: x.public_note.trim() || null, consent_text: x.consent_text.trim() || null,
        min_notice_minutes: int(x.min_notice_minutes), max_days_ahead: Math.max(int(x.max_days_ahead), 1), slot_granularity_minutes: int(x.slot_granularity_minutes),
        default_buffer_minutes: int(x.default_buffer_minutes), cancel_window_hours: int(x.cancel_window_hours), reminders_enabled: x.reminders_enabled,
        reminder_hours_before: Math.max(int(x.reminder_hours_before), 1), quiet_start: x.quiet_start, quiet_end: x.quiet_end,
        invoice_on_completion: x.invoice_on_completion, invoice_due_days: x.invoice_due_days === "" ? null : int(x.invoice_due_days),
        late_cancel_fee_percent: x.late_cancel_fee_percent || "0", no_show_fee_percent: x.no_show_fee_percent || "0", fee_product_id: x.fee_product_id || null,
        waitlist_confirm_minutes: int(x.waitlist_confirm_minutes), rebook_prompt_hours: int(x.rebook_prompt_hours), recalls_enabled: x.recalls_enabled,
        deposit_note: x.deposit_note.trim() || null, patch_test_valid_days: x.patch_test_valid_days === "" ? null : int(x.patch_test_valid_days),
        commission_excludes_tax: x.commission_excludes_tax, discount_limit_percent: x.discount_limit_percent === "" ? null : x.discount_limit_percent,
        reminder_template: x.reminder_template || null, recall_template: x.recall_template || null, rebook_template: x.rebook_template || null } }));
    },
    onSuccess: () => { void refresh(); toast(t("settings.saved"), "ok"); },
  });

  const items = useQuery({
    queryKey: ["bookings", "service-items", companyId], enabled: !!companyId && canSetup,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/service-items", { params: { query: { company_id: companyId } } })),
  });
  const sample = useQuery({
    queryKey: ["bookings", "sample-data", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/sample-data", { params: { query: { company_id: companyId } } })),
  });
  const makeSample = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/sample-data", { params: { query: { company_id: companyId } } })),
    onSuccess: () => { void refresh(); toast(t("settings.sampleMade"), "ok"); },
  });
  const dropSample = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/bookings/sample-data", { params: { query: { company_id: companyId } } })),
    onSuccess: () => { void refresh(); toast(t("settings.sampleGone"), "ok"); },
  });

  if (query.isLoading || (!d && !query.error)) return <SkeletonRows rows={6} cols={2} />;
  if (query.error || !d || !query.data) return <ErrorState message={query.error?.message} onRetry={() => void query.refetch()} />;
  const off = !canSetup;

  return (
    <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-5">
      <PageHeader title={t("settings.title")} description={t("settings.hint")}
        actions={canSetup && <Button type="submit" loading={save.isPending}>{t("save")}</Button>} />
      <Card title={t("settings.online")} description={t("settings.onlineHint")}>
        <div className="space-y-4">
          <Checkbox checked={d.online_enabled} disabled={off} onChange={(e) => set("online_enabled", e.target.checked)} label={t("settings.onlineOn")} />
          <Field label={t("settings.address")} hint={t("settings.addressHint")}>
            <div className="flex items-center gap-2">
              <span className="hidden shrink-0 text-sm text-muted sm:inline">{window.location.origin}/book/</span>
              <Input value={d.slug} disabled={off} onChange={(e) => set("slug", e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))} maxLength={60} placeholder="my-salon" />
            </div>
          </Field>
          {d.online_enabled && !d.slug && <Alert tone="warn">{t("settings.needAddress")}</Alert>}
          <FormGrid>
            <Field label={t("settings.publicName")} hint={t("settings.publicNameHint")}><Input value={d.public_name} disabled={off} onChange={(e) => set("public_name", e.target.value)} maxLength={120} /></Field>
            <Field label={t("settings.publicNote")} hint={t("settings.publicNoteHint")}><Input value={d.public_note} disabled={off} onChange={(e) => set("public_note", e.target.value)} maxLength={600} /></Field>
          </FormGrid>
          <Field label={t("settings.consent")} hint={t("settings.consentHint")}><Textarea value={d.consent_text} disabled={off} onChange={(e) => set("consent_text", e.target.value)} maxLength={600} /></Field>
          <Checkbox checked={d.auto_confirm} disabled={off} onChange={(e) => set("auto_confirm", e.target.checked)} label={t("settings.autoConfirm")} />
          <Checkbox checked={d.show_resources_publicly} disabled={off} onChange={(e) => set("show_resources_publicly", e.target.checked)} label={t("settings.showPeople")} />
          {query.data.slug && query.data.online_enabled && <ShareLink slug={query.data.slug} />}
        </div>
      </Card>
      <Card title={t("settings.rules")} description={t("settings.rulesHint")}>
        <FormGrid cols={3}>
          <Field label={t("settings.minNotice")} hint={t("settings.minNoticeHint")}><NumberInput value={d.min_notice_minutes} disabled={off} onChange={(v) => set("min_notice_minutes", v.split(".")[0] ?? "")} /></Field>
          <Field label={t("settings.maxDays")}><NumberInput value={d.max_days_ahead} disabled={off} onChange={(v) => set("max_days_ahead", v.split(".")[0] ?? "")} /></Field>
          <Field label={t("settings.granularity")} hint={t("settings.granularityHint")}>
            <Select value={d.slot_granularity_minutes} disabled={off} onChange={(e) => set("slot_granularity_minutes", e.target.value)}>
              {[5, 10, 15, 20, 30, 60].map((m) => <option key={m} value={m}>{t("settings.everyMinutes", { count: m })}</option>)}
            </Select>
          </Field>
          <Field label={t("settings.defaultBuffer")} hint={t("settings.defaultBufferHint")}><NumberInput value={d.default_buffer_minutes} disabled={off} onChange={(v) => set("default_buffer_minutes", v.split(".")[0] ?? "")} /></Field>
          <Field label={t("settings.cancelWindow")} hint={t("settings.cancelWindowHint")}><NumberInput value={d.cancel_window_hours} disabled={off} onChange={(v) => set("cancel_window_hours", v.split(".")[0] ?? "")} /></Field>
        </FormGrid>
      </Card>
      <Card title={t("settings.reminders")} description={t("settings.remindersHint")}>
        <div className="space-y-4">
          <Checkbox checked={d.reminders_enabled} disabled={off} onChange={(e) => set("reminders_enabled", e.target.checked)} label={t("settings.remindersOn")} />
          <FormGrid cols={3}>
            <Field label={t("settings.remindHours")}><NumberInput value={d.reminder_hours_before} disabled={off || !d.reminders_enabled} onChange={(v) => set("reminder_hours_before", v.split(".")[0] ?? "")} /></Field>
            <Field label={t("settings.quietStart")} hint={t("settings.quietHint")}><Input type="time" value={d.quiet_start} disabled={off} onChange={(e) => set("quiet_start", e.target.value)} /></Field>
            <Field label={t("settings.quietEnd")}><Input type="time" value={d.quiet_end} disabled={off} onChange={(e) => set("quiet_end", e.target.value)} /></Field>
          </FormGrid>
        </div>
      </Card>
      <Card title={t("settings.billing")} description={t("settings.billingHint")}>
        <div className="space-y-4">
          {!query.data.invoicing_available && <Alert tone="info">{t("settings.noInvoicing")}</Alert>}
          <Checkbox checked={d.invoice_on_completion} disabled={off || !query.data.invoicing_available} onChange={(e) => set("invoice_on_completion", e.target.checked)} label={t("settings.invoiceAuto")} />
          <Field label={t("settings.dueDays")} hint={t("settings.dueDaysHint")}><NumberInput className="max-w-[10rem]" value={d.invoice_due_days} disabled={off || !query.data.invoicing_available} onChange={(v) => set("invoice_due_days", v.split(".")[0] ?? "")} /></Field>
        </div>
      </Card>
      <Card title={t("settings.policy")} description={t("settings.policyHint")}>
        <div className="space-y-4">
          <FormGrid cols={3}>
            <Field label={t("settings.lateFee")} hint={t("settings.lateFeeHint")}><NumberInput value={d.late_cancel_fee_percent} disabled={off} onChange={(v) => set("late_cancel_fee_percent", v)} /></Field>
            <Field label={t("settings.noShowFee")} hint={t("settings.noShowFeeHint")}><NumberInput value={d.no_show_fee_percent} disabled={off} onChange={(v) => set("no_show_fee_percent", v)} /></Field>
            <Field label={t("settings.feeItem")} hint={t("settings.feeItemHint")}>
              <Select value={d.fee_product_id} disabled={off} onChange={(e) => set("fee_product_id", e.target.value)}>
                <option value="">{t("settings.noFeeItem")}</option>
                {(items.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </Select>
            </Field>
          </FormGrid>
          {(Number(d.late_cancel_fee_percent) > 0 || Number(d.no_show_fee_percent) > 0) && !d.fee_product_id && <Alert tone="warn">{t("settings.needFeeItem")}</Alert>}
          <Field label={t("settings.depositNote")} hint={t("settings.depositNoteHint")}><Input value={d.deposit_note} disabled={off} onChange={(e) => set("deposit_note", e.target.value)} maxLength={300} /></Field>
          <FormGrid cols={3}>
            <Field label={t("settings.waitConfirm")} hint={t("settings.waitConfirmHint")}><NumberInput value={d.waitlist_confirm_minutes} disabled={off} onChange={(v) => set("waitlist_confirm_minutes", v.split(".")[0] ?? "")} /></Field>
            <Field label={t("settings.patchDays")} hint={t("settings.patchDaysHint")}><NumberInput value={d.patch_test_valid_days} disabled={off} onChange={(v) => set("patch_test_valid_days", v.split(".")[0] ?? "")} /></Field>
            <Field label={t("settings.discountLimit")} hint={t("settings.discountLimitHint")}><NumberInput value={d.discount_limit_percent} disabled={off} onChange={(v) => set("discount_limit_percent", v)} /></Field>
          </FormGrid>
          <Checkbox checked={d.commission_excludes_tax} disabled={off} onChange={(e) => set("commission_excludes_tax", e.target.checked)} label={t("settings.commissionNoTax")} />
        </div>
      </Card>
      <Card title={t("settings.comeBack")} description={t("settings.comeBackHint")}>
        <div className="space-y-4">
          <Checkbox checked={d.recalls_enabled} disabled={off} onChange={(e) => set("recalls_enabled", e.target.checked)} label={t("settings.recallsOn")} />
          <FormGrid cols={3}>
            <Field label={t("settings.rebookHours")} hint={t("settings.rebookHoursHint")}><NumberInput value={d.rebook_prompt_hours} disabled={off} onChange={(v) => set("rebook_prompt_hours", v.split(".")[0] ?? "")} /></Field>
            {(Object.keys(TEMPLATES) as (keyof typeof TEMPLATES)[]).map((key) => (
              <Field key={key} label={t(`settings.wording.${key}`)}>
                <Select value={d[key]} disabled={off} onChange={(e) => set(key, e.target.value)}>
                  <option value="">{t("settings.wordingStandard")}</option>
                  {TEMPLATES[key].map((code) => <option key={code} value={code}>{t(`settings.wordingNames.${code}`)}</option>)}
                </Select>
              </Field>
            ))}
          </FormGrid>
        </div>
      </Card>
      {canSetup && (
        <Card title={t("settings.sample")} description={t("settings.sampleHint")}>
          <div className="flex flex-wrap items-center gap-3">
            {sample.data && Object.keys(sample.data).length > 0 ? (
              <>
                <span className="text-sm text-muted">{t("settings.sampleHave", { count: sample.data["appointment"] ?? 0 })}</span>
                <Button type="button" variant="secondary" loading={dropSample.isPending} onClick={() => dropSample.mutate()}>{t("settings.sampleRemove")}</Button>
              </>
            ) : (
              <Button type="button" variant="secondary" loading={makeSample.isPending} onClick={() => makeSample.mutate()}>{t("settings.sampleMake")}</Button>
            )}
          </div>
        </Card>
      )}
    </form>
  );
}

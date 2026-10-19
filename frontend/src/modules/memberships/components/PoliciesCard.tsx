import { type ReactNode, useEffect, useState } from "react";

import { api, Alert, Button, Card, ErrorState, Field, FormGrid, Input, NumberInput, Select, Skeleton, Switch, toast, unwrap, useAccess, useCan, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { ServicePicker, useSettings, type Settings } from "../hooks";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

type IntKey = "catch_up_max_periods" | "renewal_reminder_days" | "expiry_reminder_days" | "grace_days" | "auto_freeze_days" | "inactive_weeks" | "repeat_window_minutes"
  | "expiry_warning_days" | "late_cancel_hours" | "offline_valid_hours";
type MoneyKey = "points_per_unit" | "point_value" | "referral_reward";

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 border-t border-line pt-5 first:border-t-0 first:pt-0">
      <legend className="text-sm font-semibold">{title}</legend>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      {children}
    </fieldset>
  );
}

/** The company's membership policies, in small groups: credits and billing, late payments, members, classes, rewards and the door. */
export function PoliciesCard() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const hasProducts = useAccess().enabledUnits.has("products");
  const canEdit = useCan("memberships.plans");
  const q = useSettings(company?.id);
  const [draft, setDraft] = useState<Settings | null>(null);
  useEffect(() => { if (q.data) setDraft(q.data); }, [q.data]);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = { ...(draft as Settings) } as Partial<Settings>;
      delete body.company_id;
      return unwrap(api.PATCH("/api/v1/memberships/settings", { params: { query: { company_id: company?.id ?? "" } }, body: { ...body, message_language: body.message_language as "en" } }));
    },
    onSuccess: (s) => { setDraft(s); void qc.invalidateQueries({ queryKey: ["memberships-settings"] }); toast(t("policiesSaved"), "ok"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (q.error) return <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />;
  if (!draft) return <Skeleton className="h-64 w-full" />;
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setDraft({ ...draft, [key]: value });
  const int = (key: IntKey) => <NumberInput value={String(draft[key])} disabled={!canEdit} onChange={(v) => set(key, Number(v.split(".")[0] || 0))} />;
  const dec = (key: MoneyKey) => <NumberInput value={String(draft[key])} disabled={!canEdit} onChange={(v) => set(key, v)} />;
  const sw = (key: keyof Settings & ("allow_overdraw" | "prorate_first_period" | "reminders_enabled" | "birthday_messages" | "waiver_required" | "late_cancel_consumes" | "no_show_consumes" | "auto_apply_credit"), label: string, hint?: string) => (
    <div>
      <Switch checked={draft[key]} disabled={!canEdit} onChange={(v) => set(key, v)} label={label} />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
  const hour = (key: "quiet_start" | "quiet_end") => (
    <Select value={String(draft[key])} disabled={!canEdit} onChange={(e) => set(key, Number(e.target.value))}>
      {HOURS.map((h) => <option key={h} value={h}>{`${String(h).padStart(2, "0")}:00`}</option>)}
    </Select>
  );

  return (
    <Card title={t("policies")} description={t("policiesHint")}>
      <div className="space-y-5">
        {!canEdit && <Alert tone="info">{t("policiesReadOnly")}</Alert>}
        <Group title={t("pol.credits")}>
          {sw("allow_overdraw", t("allowOverdraw"), t("allowOverdrawHint"))}
          {sw("prorate_first_period", t("prorate"), t("prorateHint"))}
          <FormGrid>
            <Field label={t("catchUp")} hint={t("catchUpHint")}>{int("catch_up_max_periods")}</Field>
            <Field label={t("messageLanguage")} hint={t("messageLanguageHint")}>
              <Select value={draft.message_language} disabled={!canEdit} onChange={(e) => set("message_language", e.target.value)}>
                <option value="en">English</option><option value="sw">Kiswahili</option>
              </Select>
            </Field>
          </FormGrid>
        </Group>

        <Group title={t("pol.late")} hint={t("pol.lateHint")}>
          <FormGrid>
            <Field label={t("pol.graceDays")} hint={t("pol.graceDaysHint")}>{int("grace_days")}</Field>
            <Field label={t("pol.dunningDays")} hint={t("pol.dunningDaysHint")}>
              <Input value={draft.dunning_days} disabled={!canEdit} maxLength={60} placeholder="3, 7, 14" onChange={(e) => set("dunning_days", e.target.value)} />
            </Field>
            <Field label={t("pol.autoFreeze")} hint={t("pol.autoFreezeHint")}>{int("auto_freeze_days")}</Field>
          </FormGrid>
        </Group>

        <Group title={t("pol.members")}>
          <FormGrid>
            <Field label={t("pol.inactiveWeeks")} hint={t("pol.inactiveWeeksHint")}>{int("inactive_weeks")}</Field>
            <Field label={t("pol.expiryWarning")} hint={t("pol.expiryWarningHint")}>{int("expiry_warning_days")}</Field>
            <Field label={t("pol.repeatWindow")} hint={t("pol.repeatWindowHint")}>{int("repeat_window_minutes")}</Field>
          </FormGrid>
          {sw("birthday_messages", t("pol.birthday"), t("pol.birthdayHint"))}
          {sw("waiver_required", t("pol.termsRequired"), t("pol.termsRequiredHint"))}
        </Group>

        <Group title={t("pol.classes")}>
          <Field label={t("pol.lateCancelHours")} hint={t("pol.lateCancelHoursHint")}>{int("late_cancel_hours")}</Field>
          {sw("late_cancel_consumes", t("pol.lateCancelConsumes"))}
          {sw("no_show_consumes", t("pol.noShowConsumes"))}
        </Group>

        <Group title={t("pol.rewards")}>
          <FormGrid>
            <Field label={t("pol.referral")} hint={t("pol.referralHint")}>{dec("referral_reward")}</Field>
            <Field label={t("pol.pointsPerUnit")} hint={t("pol.pointsPerUnitHint")}>{dec("points_per_unit")}</Field>
            <Field label={t("pol.pointValue")} hint={t("pol.pointValueHint")}>{dec("point_value")}</Field>
          </FormGrid>
          {sw("auto_apply_credit", t("pol.autoCredit"), t("pol.autoCreditHint"))}
          {hasProducts && <ServicePicker value={draft.voucher_product_id ?? ""} onChange={(id) => set("voucher_product_id", id || null)} label={t("pol.voucherItem")} hint={t("pol.voucherItemHint")} clearable />}
        </Group>

        <Group title={t("pol.reminders")}>
          {sw("reminders_enabled", t("remindersOn"))}
          <FormGrid>
            <Field label={t("renewalReminderDays")} hint={t("renewalReminderDaysHint")}>{int("renewal_reminder_days")}</Field>
            <Field label={t("expiryReminderDays")} hint={t("expiryReminderDaysHint")}>{int("expiry_reminder_days")}</Field>
            <Field label={t("quietFrom")} hint={t("quietHint")}>{hour("quiet_start")}</Field>
            <Field label={t("quietTo")}>{hour("quiet_end")}</Field>
          </FormGrid>
        </Group>

        <Group title={t("pol.door")}>
          <Field label={t("pol.offlineHours")} hint={t("pol.offlineHoursHint")}>{int("offline_valid_hours")}</Field>
        </Group>

        {canEdit && <div className="flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button></div>}
      </div>
    </Card>
  );
}

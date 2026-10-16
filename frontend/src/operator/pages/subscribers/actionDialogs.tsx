import { useState } from "react";

import { Alert, Checkbox, Field, Input, NumberInput, type Schemas, Select, Textarea, formatDate, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { ActionForm } from "../../components/ActionForm";
import { PlanChoice, type PlanChoiceValue } from "../../components/PlanChoice";
import { dateToIso } from "../../helpers/format";
import { reasonOk } from "../../lib";

type Detail = Schemas["SubscriberDetail"];
type Interval = Schemas["ChangePlanIn"]["interval"];

interface DialogProps {
  code: string;
  onDone: (detail: Detail) => void;
  onClose: () => void;
}

const NO_CHOICE: PlanChoiceValue = { plan: "", interval: "", currency: "" };
const path = (code: string) => ({ params: { path: { code } } });

export function StartSubscriptionDialog({ code, onDone, onClose }: DialogProps) {
  const { t } = useTranslation("operator");
  const [choice, setChoice] = useState(NO_CHOICE);
  const [mode, setMode] = useState<"trial" | "active" | "comp">("trial");
  const [until, setUntil] = useState("");
  return (
    <ActionForm title={t("subscriber.start.title")} submitLabel={t("subscriber.start.submit")} ready={!!choice.plan} size="md" onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/subscription", {
        ...path(code),
        body: { plan_code: choice.plan, mode, interval: (choice.interval || undefined) as Interval, currency: choice.currency || undefined, comp_until: mode === "comp" ? dateToIso(until) : null },
      }))}>
      <p className="text-sm text-muted">{t("subscriber.start.intro")}</p>
      <PlanChoice value={choice} onChange={setChoice} />
      <Field label={t("subscriber.start.mode")} hint={t(`subscriber.start.modeHints.${mode}`)}>
        <Select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
          {(["trial", "active", "comp"] as const).map((m) => <option key={m} value={m}>{t(`subscriber.start.modes.${m}`)}</option>)}
        </Select>
      </Field>
      {mode === "comp" && <Field label={t("subscriber.comp.until")} hint={t("subscriber.comp.untilHint")}><Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>}
    </ActionForm>
  );
}

export function ChangePlanDialog({ code, currentPlan, onDone, onClose }: DialogProps & { currentPlan?: string }) {
  const { t } = useTranslation("operator");
  const [choice, setChoice] = useState(NO_CHOICE);
  const [effective, setEffective] = useState<"auto" | "now" | "period_end">("auto");
  const [prorated, setProrated] = useState(true);
  return (
    <ActionForm title={t("subscriber.changePlan.title")} submitLabel={t("subscriber.changePlan.submit")} ready={!!choice.plan} size="md" onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/plan", {
        ...path(code),
        body: { plan_code: choice.plan, interval: (choice.interval || undefined) as Interval, currency: choice.currency || undefined, effective, bill_prorated: prorated },
      }))}>
      {currentPlan && <p className="text-sm text-muted">{t("subscriber.changePlan.current", { plan: currentPlan })}</p>}
      <PlanChoice value={choice} onChange={setChoice} />
      <Field label={t("subscriber.changePlan.effective")} hint={t(`subscriber.changePlan.effectiveHints.${effective}`)}>
        <Select value={effective} onChange={(e) => setEffective(e.target.value as typeof effective)}>
          {(["auto", "now", "period_end"] as const).map((v) => <option key={v} value={v}>{t(`subscriber.changePlan.effectives.${v}`)}</option>)}
        </Select>
      </Field>
      <Checkbox label={t("subscriber.changePlan.prorated")} checked={prorated} onChange={(e) => setProrated(e.target.checked)} />
      <Alert tone="info">{t("subscriber.changePlan.note")}</Alert>
    </ActionForm>
  );
}

export function ExtendTrialDialog({ code, trialEnd, onDone, onClose }: DialogProps & { trialEnd?: string | null }) {
  const { t } = useTranslation("operator");
  const [days, setDays] = useState("7");
  const n = Number(days);
  return (
    <ActionForm title={t("subscriber.trial.title")} submitLabel={t("subscriber.trial.submit")} ready={Number.isInteger(n) && n >= 1 && n <= 365} onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/trial", { ...path(code), body: { days: n } }))}>
      {trialEnd && <p className="text-sm text-muted">{t("subscriber.trial.current", { date: formatDate(trialEnd) })}</p>}
      <Field label={t("subscriber.trial.days")} hint={t("subscriber.trial.daysHint")} required><NumberInput value={days} onChange={setDays} /></Field>
    </ActionForm>
  );
}

export function CompDialog({ code, onDone, onClose }: DialogProps) {
  const { t } = useTranslation("operator");
  const [choice, setChoice] = useState(NO_CHOICE);
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  return (
    <ActionForm title={t("subscriber.comp.title")} submitLabel={t("subscriber.comp.submit")} ready={reasonOk(reason)} size="md" onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/comp", { ...path(code), body: { plan_code: choice.plan || null, until: dateToIso(until), reason: reason.trim() } }))}>
      <p className="text-sm text-muted">{t("subscriber.comp.intro")}</p>
      <PlanChoice value={choice} onChange={setChoice} optionalPlan />
      <Field label={t("subscriber.comp.until")} hint={t("subscriber.comp.untilHint")}><Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      <Field label={t("common.reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} /></Field>
    </ActionForm>
  );
}

export function CouponDialog({ code, onDone, onClose }: DialogProps) {
  const { t } = useTranslation("operator");
  const [coupon, setCoupon] = useState("");
  return (
    <ActionForm title={t("subscriber.coupon.title")} submitLabel={t("subscriber.coupon.submit")} ready={coupon.trim().length >= 3} onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/coupon", { ...path(code), body: { code: coupon.trim().toUpperCase() } }))}>
      <Field label={t("subscriber.coupon.code")} hint={t("subscriber.coupon.hint")} required>
        <Input value={coupon} onChange={(e) => setCoupon(e.target.value.toUpperCase())} maxLength={40} className="font-mono" autoFocus />
      </Field>
    </ActionForm>
  );
}

export function CancelDialog({ code, onDone, onClose }: DialogProps) {
  const { t } = useTranslation("operator");
  const [atEnd, setAtEnd] = useState(true);
  const [reason, setReason] = useState("");
  return (
    <ActionForm title={t("subscriber.cancel.title")} submitLabel={t(atEnd ? "subscriber.cancel.submitEnd" : "subscriber.cancel.submitNow")} danger onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/cancel", { ...path(code), body: { at_period_end: atEnd, reason: reason.trim() || null } }))}>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">{t("subscriber.cancel.when")}</legend>
        {([true, false] as const).map((value) => (
          <label key={String(value)} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5 text-sm">
            <input type="radio" name="cancel-when" className="mt-1" checked={atEnd === value} onChange={() => setAtEnd(value)} />
            <span><span className="font-medium">{t(value ? "subscriber.cancel.atEnd" : "subscriber.cancel.now")}</span><span className="block text-xs text-muted">{t(value ? "subscriber.cancel.atEndHint" : "subscriber.cancel.nowHint")}</span></span>
          </label>
        ))}
      </fieldset>
      <Field label={t("common.reasonOptional")}><Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} /></Field>
    </ActionForm>
  );
}

export function DeleteDialog({ code, onDone, onClose }: DialogProps) {
  const { t } = useTranslation("operator");
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [early, setEarly] = useState(false);
  return (
    <ActionForm title={t("subscriber.delete.title")} submitLabel={t("subscriber.delete.submit")} danger ready={typed === code && reasonOk(reason, 10)} onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/delete", { ...path(code), body: { confirm: typed, reason: reason.trim(), early } }))}>
      <Alert tone="warn">{t("subscriber.delete.warning")}</Alert>
      <Field label={t("subscriber.delete.typeCode", { code })} required><Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} className="font-mono" /></Field>
      <Field label={t("subscriber.delete.reason")} hint={t("subscriber.delete.reasonHint")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} /></Field>
      <div className="space-y-1">
        <Checkbox label={t("subscriber.delete.early")} checked={early} onChange={(e) => setEarly(e.target.checked)} />
        <p className="pl-6 text-xs text-muted">{t("subscriber.delete.earlyHint")}</p>
      </div>
    </ActionForm>
  );
}

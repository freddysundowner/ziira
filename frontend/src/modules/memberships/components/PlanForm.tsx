import { type FormEvent, useEffect, useState } from "react";

import {
  api, Alert, Button, Checkbox, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, Switch, Tabs, Textarea, toast, unwrap, useAccess, useCompany,
  useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { type AccessWindow, readWindows, windowsProblem } from "../gymLogic";
import { ServicePicker } from "../hooks";
import type { Plan } from "../hooks";
import { AccessWindows } from "./AccessWindows";

const split = (text: string): string[] => text.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
const whole = (v: string): string => v.split(".")[0] ?? "";
type Section = "basics" | "contract" | "access" | "holds" | "extras";
const SECTIONS: readonly Section[] = ["basics", "contract", "access", "holds", "extras"];
type Kind = "recurring" | "fixed_term" | "pass";

/** Create or edit a plan, in five small sections. A plan's code and billing interval are fixed once it exists; members keep the price they started with. */
export function PlanForm({ open, onClose, plan }: { open: boolean; onClose: () => void; plan?: Plan }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const hasProducts = useAccess().enabledUnits.has("products");
  const editing = !!plan;
  const initial = {
    code: plan?.code ?? "", name: plan?.name ?? "", description: plan?.description ?? "", fee: plan?.fee ?? "", billing_interval: plan?.billing_interval ?? "month",
    kind: plan?.kind ?? "recurring", valid_days: plan?.valid_days ? String(plan.valid_days) : "", term_periods: plan?.term_periods ? String(plan.term_periods) : "",
    notice_days: plan ? String(plan.notice_days) : "0", early_exit_fee: plan?.early_exit_fee ?? "0", joining_fee: plan?.joining_fee ?? "0",
    freeze_max_days: plan?.freeze_max_days === null || plan?.freeze_max_days === undefined ? "" : String(plan.freeze_max_days), freeze_fee: plan?.freeze_fee ?? "0",
    prorate: plan?.prorate === null || plan?.prorate === undefined ? "default" : plan.prorate ? "yes" : "no",
    classes_mode: plan?.classes_mode ?? "none", guests: plan ? String(plan.guest_passes_per_period) : "0",
    credits_per_period: plan?.credits_per_period ?? "0", discount_percent: plan?.discount_percent ?? "0", covered: (plan?.covered_services ?? []).join(", "),
    terms: plan?.terms ?? "", status: plan?.status ?? "active",
  };
  const f = useFormState(initial);
  const [section, setSection] = useState<Section>("basics");
  const [rollover, setRollover] = useState(plan?.rollover ?? false);
  const [trial, setTrial] = useState(plan?.is_trial ?? false);
  const [gym, setGym] = useState(plan?.gym_access ?? true);
  const [product, setProduct] = useState(plan?.service_product_id ?? "");
  const [joiningProduct, setJoiningProduct] = useState(plan?.joining_fee_product_id ?? "");
  const [windows, setWindows] = useState<AccessWindow[]>(readWindows(plan?.access_rules));
  const [branchIds, setBranchIds] = useState<string[]>(plan?.branch_ids ?? []);
  const { reset } = f;
  useEffect(() => {
    if (!open) return;
    reset(); setSection("basics"); setRollover(plan?.rollover ?? false); setTrial(plan?.is_trial ?? false); setGym(plan?.gym_access ?? true);
    setProduct(plan?.service_product_id ?? ""); setJoiningProduct(plan?.joining_fee_product_id ?? ""); setWindows(readWindows(plan?.access_rules)); setBranchIds(plan?.branch_ids ?? []);
  }, [open, plan?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const kind = f.values.kind as Kind;
  const isPass = kind === "pass";
  const problem = windowsProblem(windows);
  const branches = company?.branches ?? [];

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const common = {
        fee: v.fee || "0", credits_per_period: v.credits_per_period || "0", discount_percent: v.discount_percent || "0", covered_services: split(v.covered), rollover,
        service_product_id: product || null, terms: orNull(v.terms), kind, valid_days: isPass && v.valid_days ? Number(v.valid_days) : null, is_trial: isPass && trial,
        term_periods: kind === "fixed_term" && v.term_periods ? Number(v.term_periods) : null, notice_days: Number(v.notice_days || 0), early_exit_fee: v.early_exit_fee || "0",
        joining_fee: isPass ? "0" : v.joining_fee || "0", joining_fee_product_id: joiningProduct || null,
        freeze_max_days: v.freeze_max_days === "" ? null : Number(v.freeze_max_days), freeze_fee: v.freeze_fee || "0",
        prorate: v.prorate === "default" ? null : v.prorate === "yes",
        access_rules: windows.map((w) => ({ days: w.days, from: w.from, to: w.to })), branch_ids: branchIds, gym_access: gym,
        classes_mode: v.classes_mode as "none", guest_passes_per_period: Number(v.guests || 0), description: orNull(v.description),
        is_example: false,
      };
      return plan
        ? unwrap(api.PATCH("/api/v1/memberships/plans/{plan_id}", { params: { path: { plan_id: plan.id } }, body: { ...common, name: v.name.trim(), status: v.status as "active" } }))
        : unwrap(api.POST("/api/v1/memberships/plans", { body: { ...common, company_id: company?.id ?? "", code: v.code.trim(), name: v.name.trim(), billing_interval: (isPass ? "month" : v.billing_interval) as "month" } }));
    },
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["memberships-plans"] });
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t(editing ? "planSaved" : "planCreated", { name: p.name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (problem) { setSection("access"); return; } save.mutate(); };
  const toggleBranch = (id: string) => setBranchIds((all) => (all.includes(id) ? all.filter((x) => x !== id) : [...all, id]));

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("editPlan") : t("newPlan")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="plan-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="plan-form" onSubmit={submit} className="space-y-4">
        <Tabs value={section} onChange={setSection} tabs={SECTIONS.map((id) => ({ id, label: t(`planx.sections.${id}`) }))} />
        {plan?.is_example && <Alert tone="warn">{t("planx.exampleNote")}</Alert>}

        <div className="space-y-4" hidden={section !== "basics"}>
          <FormGrid>
            <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={200} /></Field>
            <Field label={t("code")} hint={editing ? t("codeFixed") : t("codeHint")} error={f.error("code")}><Input {...f.bind("code")} required disabled={editing} maxLength={30} /></Field>
          </FormGrid>
          <Field label={t("planx.kind")} hint={t(`planx.kindHint.${kind}`)}>
            <Select {...f.bind("kind")}>{(["recurring", "fixed_term", "pass"] as const).map((k) => <option key={k} value={k}>{t(`planx.kinds.${k}`)}</option>)}</Select>
          </Field>
          <FormGrid>
            <Field label={t("fee")} required error={f.error("fee")}><NumberInput value={f.values.fee} onChange={(v) => f.set("fee", v)} required /></Field>
            {isPass
              ? <Field label={t("planx.validDays")} hint={t("planx.validDaysHint")} error={f.error("valid_days")}><NumberInput value={f.values.valid_days} onChange={(v) => f.set("valid_days", whole(v))} /></Field>
              : (
                <Field label={t("billedEvery")} hint={editing ? t("intervalFixed") : undefined} error={f.error("billing_interval")}>
                  <Select {...f.bind("billing_interval")} disabled={editing}>{(["month", "quarter", "year"] as const).map((i) => <option key={i} value={i}>{t(`intervals.${i}`)}</option>)}</Select>
                </Field>)}
          </FormGrid>
          {isPass && <Switch checked={trial} onChange={setTrial} label={t("planx.isTrial")} />}
          <Field label={t("planx.description")} hint={t("planx.descriptionHint")} error={f.error("description")}><Textarea rows={2} maxLength={1000} {...f.bind("description")} /></Field>
          {hasProducts && <ServicePicker value={product} onChange={setProduct} label={t("invoicedAs")} hint={t("invoicedAsHint")} clearable />}
          {editing && (
            <Field label={t("status")} hint={t("retireHint")}>
              <Select {...f.bind("status")}>{(["active", "retired"] as const).map((s) => <option key={s} value={s}>{t(`catalogueStatus.${s}`)}</option>)}</Select>
            </Field>
          )}
        </div>

        <div className="space-y-4" hidden={section !== "contract"}>
          {isPass && <Alert tone="info">{t("planx.passNoContract")}</Alert>}
          {kind === "fixed_term" && (
            <Field label={t("planx.termPeriods")} hint={t("planx.termPeriodsHint")} error={f.error("term_periods")}><NumberInput value={f.values.term_periods} onChange={(v) => f.set("term_periods", whole(v))} /></Field>
          )}
          {!isPass && (
            <>
              <FormGrid>
                <Field label={t("planx.noticeDays")} hint={t("planx.noticeDaysHint")} error={f.error("notice_days")}><NumberInput value={f.values.notice_days} onChange={(v) => f.set("notice_days", whole(v))} /></Field>
                <Field label={t("planx.exitFee")} hint={t("planx.exitFeeHint")} error={f.error("early_exit_fee")}><NumberInput value={f.values.early_exit_fee} onChange={(v) => f.set("early_exit_fee", v)} /></Field>
              </FormGrid>
              <FormGrid>
                <Field label={t("planx.joiningFee")} hint={t("planx.joiningFeeHint")} error={f.error("joining_fee")}><NumberInput value={f.values.joining_fee} onChange={(v) => f.set("joining_fee", v)} /></Field>
                {hasProducts && <ServicePicker value={joiningProduct} onChange={setJoiningProduct} label={t("planx.joiningFeeAs")} clearable />}
              </FormGrid>
              <Field label={t("planx.prorate")} hint={t("planx.prorateHint")}>
                <Select {...f.bind("prorate")}>{(["default", "yes", "no"] as const).map((x) => <option key={x} value={x}>{t(`planx.prorateOptions.${x}`)}</option>)}</Select>
              </Field>
            </>
          )}
          <Field label={t("terms")} hint={t("termsHint")} error={f.error("terms")}><Textarea rows={3} maxLength={4000} {...f.bind("terms")} /></Field>
        </div>

        <div className="space-y-4" hidden={section !== "access"}>
          <Switch checked={gym} onChange={setGym} label={t("planx.gymAccess")} />
          <div>
            <p className="mb-1 text-sm font-semibold">{t("planx.windows")}</p>
            <p className="mb-2 text-xs text-muted">{t("planx.windowsHint")}</p>
            <AccessWindows value={windows} onChange={setWindows} />
            {problem && <p role="alert" className="mt-2 text-sm text-bad">{t(`planx.windowProblem.${problem}`)}</p>}
          </div>
          {branches.length > 1 && (
            <div>
              <p className="mb-1 text-sm font-semibold">{t("planx.branches")}</p>
              <p className="mb-2 text-xs text-muted">{t("planx.branchesHint")}</p>
              <div className="space-y-1">{branches.map((b) => <Checkbox key={b.id} checked={branchIds.includes(b.id)} onChange={() => toggleBranch(b.id)} label={b.name} />)}</div>
            </div>
          )}
          <Field label={t("planx.classes")} hint={t("planx.classesHint")}>
            <Select {...f.bind("classes_mode")}>{(["none", "included", "credits"] as const).map((x) => <option key={x} value={x}>{t(`planx.classesOptions.${x}`)}</option>)}</Select>
          </Field>
          <Field label={t("planx.guests")} hint={t("planx.guestsHint")}><NumberInput value={f.values.guests} onChange={(v) => f.set("guests", whole(v))} /></Field>
        </div>

        <div className="space-y-4" hidden={section !== "holds"}>
          {isPass ? <Alert tone="info">{t("planx.passNoHolds")}</Alert> : (
            <>
              <Field label={t("planx.freezeMax")} hint={t("planx.freezeMaxHint")} error={f.error("freeze_max_days")}><NumberInput value={f.values.freeze_max_days} onChange={(v) => f.set("freeze_max_days", whole(v))} /></Field>
              <Field label={t("planx.freezeFee")} hint={t("planx.freezeFeeHint")} error={f.error("freeze_fee")}><NumberInput value={f.values.freeze_fee} onChange={(v) => f.set("freeze_fee", v)} /></Field>
            </>
          )}
        </div>

        <div className="space-y-4" hidden={section !== "extras"}>
          <FormGrid>
            <Field label={t("creditsPerPeriod")} hint={t("creditsPerPeriodHint")} error={f.error("credits_per_period")}><NumberInput value={f.values.credits_per_period} onChange={(v) => f.set("credits_per_period", v)} /></Field>
            <Field label={t("discountPercent")} hint={t("discountPercentHint")} error={f.error("discount_percent")}><NumberInput value={f.values.discount_percent} onChange={(v) => f.set("discount_percent", v)} /></Field>
          </FormGrid>
          <Field label={t("coveredServices")} hint={t("coveredServicesHint")} error={f.error("covered_services")}><Input {...f.bind("covered")} placeholder={t("coveredPlaceholder")} /></Field>
          <Switch checked={rollover} onChange={setRollover} label={t("rollover")} />
        </div>
      </form>
    </Drawer>
  );
}

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Alert, Button, Card, Checkbox, type Edition, ErrorState, Field, FormGrid, Input, NumberInput, PageHeader, Select, Skeleton, Switch, Textarea, toast, useTranslation, useUnsavedWarning } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useEditions, usePlanDetail, usePlatformUnits, useUnitSales } from "../../catalog";
import { INTERVALS, type Interval } from "../../helpers/format";
import { changedSales, explicitUnits, saleCurrencies, saleProblems, salesToForm, sellableUnits, toggleUnit, toSaleIn, type UnitInfo, type UnitSaleForm, withRequired } from "../../helpers/planUnits";
import { EXTRA_LIMITS, emptyPlanForm, type PlanFormValues, planProblems, planToForm, toPlanIn, toPlanPatch } from "../../helpers/plan";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";
import { PricesPanel } from "./PricesPanel";
import { UnitsCard } from "./UnitsCard";

/** Create a plan (`/plans/new`) or change one (`/plans/edit/:code`), with its price table when it exists. */
export default function PlanEditorPage() {
  const { t } = useTranslation("operator");
  const code = useParams().code ?? "";
  const detail = usePlanDetail(code);
  const units = usePlatformUnits();
  const sales = useUnitSales();
  if (code && detail.isPending) return <PageSkeleton />;
  if (detail.isError) return <ErrorState title={t("plans.editor.loadFailed")} message={detail.error.message} onRetry={() => void detail.refetch()} />;
  if (units.isError || sales.isError) {
    const failure = units.error ?? sales.error;
    return <ErrorState title={t("plans.editor.unitsFailed")} message={failure?.message} onRetry={() => { void units.refetch(); void sales.refetch(); }} />;
  }
  if (!units.data || !sales.data) return <PageSkeleton />;
  const info: UnitInfo[] = sellableUnits(units.data);
  const world = { units: info, sales: salesToForm(sales.data.units), currencies: sales.data.currencies };
  if (!code) return <PlanForm initial={emptyPlanForm()} creating world={world} />;
  const initial = { ...planToForm(detail.data!), units: explicitUnits(detail.data!.units_included, info), addon_units: [], edition: "" };
  return <PlanForm key={`${detail.data!.updated_at}:${sales.dataUpdatedAt}`} initial={initial} creating={false} detail={detail.data} world={world} />;
}

function PageSkeleton() {
  return <div className="space-y-3"><Skeleton className="h-8 w-64" /><Skeleton className="h-64 w-full" /></div>;
}

interface World { units: UnitInfo[]; sales: Record<string, UnitSaleForm>; currencies: string[] }

function PlanForm({ initial, creating, detail, world }: { initial: PlanFormValues; creating: boolean; detail?: NonNullable<ReturnType<typeof usePlanDetail>["data"]>; world: World }) {
  const { t } = useTranslation("operator");
  const navigate = useNavigate();
  const refresh = useRefreshOperator();
  const canEdit = useOperatorCan("platform.plans");
  const editions = useEditions();
  const [values, setValues] = useState(initial);
  const [sales, setSales] = useState(world.sales);
  const [added, setAdded] = useState<string[]>([]);
  const [showErrors, setShowErrors] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const known = new Set(world.units.map((u) => u.name));
  const effective = withRequired(values.units, world.units);
  const errors = planProblems({ ...values, units: effective }, creating);
  const saleErrors = saleProblems(sales, effective);
  const planDirty = JSON.stringify(values) !== JSON.stringify(initial);
  const salesDirty = changedSales(sales, world.sales);
  const dirty = planDirty || salesDirty.length > 0;
  useUnsavedWarning(dirty);

  const set = <K extends keyof PlanFormValues>(key: K, value: PlanFormValues[K]) => { setValues((v) => ({ ...v, [key]: value })); setProblem(null); };
  const err = (key: string) => (showErrors && errors[key] ? t(`plans.editor.errors.${errors[key]}`) : null);
  const toggleInterval = (i: Interval) => set("intervals", values.intervals.includes(i) ? values.intervals.filter((x) => x !== i) : INTERVALS.filter((x) => x === i || values.intervals.includes(x)));
  const applyEdition = (edition: Edition) => { set("units", [...new Set([...values.units, ...edition.units])]); toast(t("plans.editor.startDone", { name: edition.title }), "ok"); };

  const save = useChange(
    async () => {
      // The prices of units sold on their own come first: they belong to the platform, not to this plan.
      for (const unit of salesDirty) await opUnwrap(opApi.PUT("/api/v1/operator/unit-sales/{unit}", { params: { path: { unit } }, body: toSaleIn(sales[unit] ?? { offered: false, prices: {}, tax_inclusive: false }, world.sales[unit]) }));
      const body = { ...values, units: effective, addon_units: [], edition: "" };
      if (!creating) {
        if (!planDirty) return detail!;
        return opUnwrap(opApi.PATCH("/api/v1/operator/plans/{code}", { params: { path: { code: initial.code } }, body: toPlanPatch(body) }));
      }
      return opUnwrap(opApi.POST("/api/v1/operator/plans", { body: toPlanIn(body) }));
    },
    {
      onSuccess: (plan) => {
        toast(t(creating ? "plans.editor.created" : "plans.editor.saved", { name: plan.name }), "ok");
        refresh();
        if (creating) navigate(`/operator/plans/edit/${encodeURIComponent(plan.code)}`, { replace: true });
      },
      onError: (error) => setProblem(error.message),
    },
  );
  const submit = () => {
    if (!canEdit || save.isPending) return;
    setProblem(null);
    if (Object.keys(errors).length > 0 || Object.keys(saleErrors).length > 0) { setShowErrors(true); return; }
    save.mutate(undefined);
  };
  const undo = () => { setValues(initial); setSales(world.sales); setShowErrors(false); setProblem(null); };

  const planCode = initial.code;
  return (
    <>
      <PageHeader title={creating ? t("plans.editor.newTitle") : values.name || planCode} description={creating ? t("plans.editor.newHint") : <span className="font-mono">{planCode}</span>}
        back={{ to: "/operator/plans", label: t("plans.editor.back") }} />
      {!canEdit && <Alert tone="info" className="mb-4">{t("plans.editor.readOnly")}</Alert>}
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <fieldset disabled={!canEdit} className="space-y-4">
          <Card title={t("plans.editor.basics")}>
            <FormGrid>
              <Field label={t("plans.editor.code")} hint={creating ? t("plans.editor.codeHint") : t("plans.editor.codeFixed")} error={err("code")} required={creating}>
                <Input value={values.code} onChange={(e) => set("code", e.target.value)} readOnly={!creating} maxLength={40} className="font-mono" autoComplete="off" />
              </Field>
              <Field label={t("plans.editor.name")} error={err("name")} required><Input value={values.name} onChange={(e) => set("name", e.target.value)} maxLength={80} /></Field>
              <Field label={t("plans.editor.description")} className="sm:col-span-2"><Textarea value={values.description} onChange={(e) => set("description", e.target.value)} rows={2} maxLength={1000} /></Field>
              <Field label={t("plans.editor.sortOrder")} hint={t("plans.editor.sortOrderHint")} error={err("sort_order")}><NumberInput value={values.sort_order} onChange={(v) => set("sort_order", v)} /></Field>
            </FormGrid>
          </Card>

          <UnitsCard units={world.units} loading={false} error={null} onRetry={() => undefined} chosen={values.units} missing={values.units.filter((n) => !known.has(n))}
            sales={sales} currencies={saleCurrencies(world.currencies, sales, added)} problems={showErrors ? saleErrors : {}} editions={editions.data ?? []} disabled={!canEdit}
            onToggle={(name) => set("units", toggleUnit(values.units, name))} onSale={(name, next) => { setSales((m) => ({ ...m, [name]: next })); setProblem(null); }}
            onBulkSales={(next) => { setSales(next); setProblem(null); }}
            onCurrency={(code) => setAdded((a) => [...new Set([...a, code])])} onEdition={applyEdition} />
          {err("units") && <Alert tone="bad">{err("units")}</Alert>}

          <Card title={t("plans.editor.limits")} description={t("plans.editor.limitsHint")}>
            <FormGrid cols={3}>
              {(["max_users", "max_branches", "max_companies"] as const).map((k) => (
                <Field key={k} label={t(`plans.editor.${k}`)} error={err(k)}><NumberInput value={values[k]} placeholder={t("plans.unlimited")} onChange={(v) => set(k, v)} /></Field>
              ))}
              {EXTRA_LIMITS.map((k) => (
                <Field key={k} label={t(`plans.editor.extra.${k}`)} error={err(k)}>
                  <NumberInput value={values.limits[k] ?? ""} placeholder={t("plans.unlimited")} onChange={(v) => set("limits", { ...values.limits, [k]: v })} />
                </Field>
              ))}
            </FormGrid>
          </Card>

          <Card title={t("plans.editor.billing")}>
            <FormGrid>
              <Field label={t("plans.editor.trialDays")} hint={t("plans.editor.trialDaysHint")} error={err("trial_days")}><NumberInput value={values.trial_days} onChange={(v) => set("trial_days", v)} /></Field>
              <fieldset>
                <legend className="mb-1.5 text-sm font-medium">{t("plans.editor.intervals")}</legend>
                <div className="flex flex-wrap gap-4">
                  {INTERVALS.map((i) => <Checkbox key={i} label={t(`interval.${i}`)} checked={values.intervals.includes(i)} onChange={() => toggleInterval(i)} />)}
                </div>
                {err("intervals") ? <p role="alert" className="mt-1 text-xs text-bad">{err("intervals")}</p> : <p className="mt-1 text-xs text-muted">{t("plans.editor.intervalsHint")}</p>}
              </fieldset>
            </FormGrid>
          </Card>

          <Card title={t("plans.editor.showing")}>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <Switch checked={values.is_public} onChange={(v) => set("is_public", v)} label={t("plans.editor.public")} />
                <div><p className="text-sm font-medium">{t("plans.editor.public")}</p><p className="text-xs text-muted">{t("plans.editor.publicHint")}</p></div>
              </div>
              <Field label={t("plans.editor.highlights")} hint={t("plans.editor.highlightsHint")} error={err("highlights")}>
                <Textarea value={values.highlights} onChange={(e) => set("highlights", e.target.value)} rows={4} />
              </Field>
              {!creating && (
                <Field label={t("plans.editor.state")} hint={values.status === "retired" ? t("plans.editor.retiredHint") : t("plans.editor.activeHint")}>
                  <Select value={values.status} onChange={(e) => set("status", e.target.value as "active" | "retired")}>
                    <option value="active">{t("plans.statuses.active")}</option>
                    <option value="retired">{t("plans.statuses.retired")}</option>
                  </Select>
                </Field>
              )}
              {!creating && !values.is_public && <p className="text-xs text-muted">{t("plans.editor.hiddenNote")}</p>}
            </div>
          </Card>
        </fieldset>

        {problem && <Alert tone="bad">{problem}</Alert>}
        {showErrors && (Object.keys(errors).length > 0 || Object.keys(saleErrors).length > 0) && <Alert tone="bad">{t("plans.editor.fixErrors")}</Alert>}
        {canEdit && (
          <div className="sticky bottom-0 -mx-1 flex justify-end gap-2 border-t border-line bg-bg/95 px-1 py-3 backdrop-blur">
            {dirty && !creating && <Button variant="ghost" onClick={undo}>{t("billing.settings.undo")}</Button>}
            <Button type="submit" loading={save.isPending} disabled={!creating && !dirty}>{t(creating ? "plans.editor.create" : "plans.editor.save")}</Button>
          </div>
        )}
      </form>

      {detail ? (
        <section className="mt-6">
          <h2 className="mb-2 text-base font-semibold">{t("plans.price.title")}</h2>
          <PlanPrices detail={detail} canEdit={canEdit} />
        </section>
      ) : (
        <Alert tone="info" className="mt-6">{t("plans.editor.pricesAfter")}</Alert>
      )}
    </>
  );
}

function PlanPrices({ detail, canEdit }: { detail: NonNullable<ReturnType<typeof usePlanDetail>["data"]>; canEdit: boolean }) {
  const code = detail.code;
  return (
    <PricesPanel prices={detail.prices} current={detail.current_prices} intervals={detail.intervals} canEdit={canEdit}
      add={(body) => opUnwrap(opApi.POST("/api/v1/operator/plans/{code}/prices", { params: { path: { code } }, body }))}
      remove={(id) => opUnwrap(opApi.DELETE("/api/v1/operator/plans/{code}/prices/{price_id}", { params: { path: { code, price_id: id } } }))} />
  );
}

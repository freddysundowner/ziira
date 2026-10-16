import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  Alert, Badge, Button, type Column, DataTable, Drawer, Field, FormGrid, formatDate, Input, NumberInput, percent, type Schemas, Select, toast, useTranslation,
} from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usePlans } from "../../catalog";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { couponProblems, type CouponForm, emptyCouponForm, toCouponIn } from "../../helpers/coupon";
import { moneyMap } from "../../helpers/format";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";

type Coupon = Schemas["CouponOut"];

export default function CouponsTab() {
  const { t } = useTranslation("operator");
  const canEdit = useOperatorCan("platform.plans");
  const refresh = useRefreshOperator();
  const [creating, setCreating] = useState(false);
  const [toggling, setToggling] = useState<Coupon | null>(null);
  const coupons = useQuery({ queryKey: ["operator", "coupons"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/coupons")) });

  const columns: Column<Coupon>[] = [
    { header: t("plans.coupons.code"), cell: (c) => <div className="min-w-0"><p className="font-mono text-sm font-medium">{c.code}</p>{c.description && <p className="truncate text-xs text-muted">{c.description}</p>}</div> },
    { header: t("plans.coupons.discount"), cell: (c) => <span className="text-sm">{c.percent_off ? t("plans.coupons.percentOff", { value: percent(c.percent_off) }) : moneyMap(c.amounts)}</span> },
    { header: t("plans.coupons.duration"), hideBelow: "md", cell: (c) => <span className="text-sm">{t(`plans.coupons.durations.${c.duration}`)}{c.duration === "repeating" && c.duration_periods ? ` (${c.duration_periods})` : ""}</span> },
    { header: t("plans.coupons.used"), align: "right", hideBelow: "sm", cell: (c) => <span className="tnum text-sm">{c.redeemed}{c.max_redemptions ? ` / ${c.max_redemptions}` : ""}</span> },
    { header: t("plans.coupons.expires"), hideBelow: "lg", cell: (c) => <span className="text-sm">{c.expires_at ? formatDate(c.expires_at) : "-"}</span> },
    { header: t("plans.coupons.plans"), hideBelow: "lg", cell: (c) => <span className="text-xs text-muted">{c.plan_codes.length ? c.plan_codes.join(", ") : t("plans.coupons.allPlans")}</span> },
    { header: t("plans.status"), cell: (c) => <Badge tone={c.status === "active" ? "ok" : "neutral"}>{t(`plans.coupons.statuses.${c.status}`, c.status)}</Badge> },
    {
      header: "", align: "right",
      cell: (c) => canEdit ? <Button size="sm" variant="secondary" onClick={() => setToggling(c)}>{t(c.status === "active" ? "plans.coupons.disable" : "plans.coupons.enable")}</Button> : null,
    },
  ];

  return (
    <>
      <DataTable rows={coupons.data} columns={columns} rowKey={(c) => c.id} loading={coupons.isPending} error={coupons.isError ? coupons.error.message : null} onRetry={() => void coupons.refetch()}
        searchText={(c) => `${c.code} ${c.description}`} searchPlaceholder={t("plans.coupons.search")} pageSize={20}
        empty={{ title: t("plans.coupons.empty"), hint: canEdit ? t("plans.coupons.emptyHint") : undefined }}
        toolbar={canEdit ? <Button className="ml-auto" size="sm" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> {t("plans.coupons.new")}</Button> : undefined} />
      {creating && <CouponDrawer onClose={() => setCreating(false)} />}
      {toggling && (
        <ChangeConfirm title={t(toggling.status === "active" ? "plans.coupons.disableTitle" : "plans.coupons.enableTitle", { code: toggling.code })}
          message={<p>{t(toggling.status === "active" ? "plans.coupons.disableMessage" : "plans.coupons.enableMessage")}</p>}
          confirmLabel={t(toggling.status === "active" ? "plans.coupons.disable" : "plans.coupons.enable")} danger={toggling.status === "active"}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/coupons/{code}/status", { params: { path: { code: toggling.code } }, body: { status: toggling.status === "active" ? "disabled" : "active" } }))}
          onDone={() => { toast(t("plans.coupons.updated"), "ok"); refresh(); }} onClose={() => setToggling(null)} />
      )}
    </>
  );
}

function CouponDrawer({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const plans = usePlans();
  const [f, setF] = useState<CouponForm>(emptyCouponForm());
  const [showErrors, setShowErrors] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const errors = couponProblems(f);
  const patch = (p: Partial<CouponForm>) => { setF((v) => ({ ...v, ...p })); setProblem(null); };
  const err = (key: string) => (showErrors && errors[key] ? t(`plans.coupons.errors.${errors[key]}`) : null);

  const create = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/coupons", { body: toCouponIn(f) })), {
    onSuccess: (coupon) => { toast(t("plans.coupons.created", { code: coupon.code }), "ok"); refresh(); onClose(); },
    onError: (error) => setProblem(error.message),
  });
  const submit = () => {
    if (create.isPending) return;
    if (Object.keys(errors).length > 0) { setShowErrors(true); return; }
    create.mutate(undefined);
  };
  const setRow = (i: number, p: Partial<CouponForm["amounts"][number]>) => patch({ amounts: f.amounts.map((r, n) => (n === i ? { ...r, ...p } : r)) });

  return (
    <Drawer open onClose={onClose} title={t("plans.coupons.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="coupon-form" loading={create.isPending}>{t("plans.coupons.create")}</Button></>}>
      <form id="coupon-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label={t("plans.coupons.code")} hint={t("plans.coupons.codeHint")} error={err("code")} required>
          <Input value={f.code} onChange={(e) => patch({ code: e.target.value.toUpperCase() })} maxLength={40} className="font-mono" autoComplete="off" autoFocus />
        </Field>
        <Field label={t("plans.coupons.description")}><Input value={f.description} onChange={(e) => patch({ description: e.target.value })} maxLength={300} /></Field>

        <Field label={t("plans.coupons.kind")}>
          <Select value={f.kind} onChange={(e) => patch({ kind: e.target.value as CouponForm["kind"] })}>
            <option value="percent">{t("plans.coupons.kinds.percent")}</option>
            <option value="fixed">{t("plans.coupons.kinds.fixed")}</option>
          </Select>
        </Field>
        {f.kind === "percent" ? (
          <Field label={t("plans.coupons.percent")} error={err("percent")} required><NumberInput value={f.percent} onChange={(v) => patch({ percent: v })} /></Field>
        ) : (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("plans.coupons.amounts")}</legend>
            <p className="text-xs text-muted">{t("plans.coupons.amountsHint")}</p>
            {f.amounts.map((row, i) => (
              <div key={i} className="grid grid-cols-[6rem_1fr_auto] items-end gap-2">
                <Field label={t("plans.price.currency")}><Input value={row.currency} onChange={(e) => setRow(i, { currency: e.target.value.toUpperCase() })} maxLength={3} className="font-mono uppercase" /></Field>
                <Field label={t("plans.price.amount")}><NumberInput value={row.amount} onChange={(v) => setRow(i, { amount: v })} /></Field>
                <Button variant="ghost" size="sm" aria-label={t("plans.coupons.removeAmount")} disabled={f.amounts.length === 1} onClick={() => patch({ amounts: f.amounts.filter((_, n) => n !== i) })}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
            {err("amounts") && <p role="alert" className="text-xs text-bad">{err("amounts")}</p>}
            <Button size="sm" variant="secondary" onClick={() => patch({ amounts: [...f.amounts, { currency: "", amount: "" }] })}><Plus className="h-4 w-4" /> {t("plans.coupons.addAmount")}</Button>
          </fieldset>
        )}

        <FormGrid>
          <Field label={t("plans.coupons.duration")} hint={t(`plans.coupons.durationHints.${f.duration}`)}>
            <Select value={f.duration} onChange={(e) => patch({ duration: e.target.value as CouponForm["duration"] })}>
              {(["once", "repeating", "forever"] as const).map((d) => <option key={d} value={d}>{t(`plans.coupons.durations.${d}`)}</option>)}
            </Select>
          </Field>
          {f.duration === "repeating" && <Field label={t("plans.coupons.periods")} error={err("periods")} required><NumberInput value={f.periods} onChange={(v) => patch({ periods: v })} /></Field>}
          <Field label={t("plans.coupons.maxRedemptions")} hint={t("plans.coupons.maxHint")} error={err("max")}><NumberInput value={f.max} onChange={(v) => patch({ max: v })} /></Field>
          <Field label={t("plans.coupons.expires")} hint={t("plans.coupons.expiresHint")}><Input type="date" value={f.expires} onChange={(e) => patch({ expires: e.target.value })} /></Field>
        </FormGrid>

        <fieldset>
          <legend className="text-sm font-medium">{t("plans.coupons.restrict")}</legend>
          <p className="mb-1 text-xs text-muted">{t("plans.coupons.restrictHint")}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {(plans.data ?? []).map((p) => (
              <label key={p.code} className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4 rounded border-line accent-[rgb(var(--brand))]" checked={f.plans.includes(p.code)}
                  onChange={() => patch({ plans: f.plans.includes(p.code) ? f.plans.filter((c) => c !== p.code) : [...f.plans, p.code] })} />
                {p.name}
              </label>
            ))}
          </div>
        </fieldset>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Drawer>
  );
}

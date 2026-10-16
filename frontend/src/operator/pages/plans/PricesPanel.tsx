import { useState } from "react";

import { Alert, Badge, type BadgeTone, Button, type Column, DataTable, Checkbox, Field, FormGrid, formatDate, Input, money, NumberInput, Select, toast, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { emptyPriceForm, type PriceForm, priceProblems, priceState, type PriceState, toPriceIn } from "../../helpers/price";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";

type Price = PlatformSchema<"PriceOut">;
type PriceBody = ReturnType<typeof toPriceIn>;
const TONES: Record<PriceState, BadgeTone> = { current: "ok", scheduled: "info", withdrawn: "bad", superseded: "neutral" };

/**
 * A plan's or add-on's prices: what is in force now, what is scheduled, and the whole history. Prices are never edited:
 * a new row from a date replaces the old one from that date, and only a row that has not started can be taken back.
 */
export function PricesPanel({ prices, current, intervals, canEdit, add, remove }: {
  prices: Price[];
  current: Price[];
  intervals: string[];
  canEdit: boolean;
  add: (body: PriceBody) => Promise<unknown>;
  remove: (id: string) => Promise<unknown>;
}) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const currentIds = new Set(current.map((p) => p.id).filter((id): id is string => !!id));
  const [form, setForm] = useState<PriceForm>(emptyPriceForm(intervals[0]));
  const [showErrors, setShowErrors] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Price | null>(null);
  const errors = priceProblems(form);
  const patch = (p: Partial<PriceForm>) => { setForm((f) => ({ ...f, ...p })); setProblem(null); };

  const save = useChange(() => add(toPriceIn(form)), {
    onSuccess: () => { toast(t("plans.price.added"), "ok"); setForm(emptyPriceForm(intervals[0])); setShowErrors(false); refresh(); },
    onError: (error) => setProblem(error.message),
  });

  const columns: Column<Price>[] = [
    { header: t("plans.price.currency"), cell: (p) => <span className="font-mono text-sm">{p.currency}</span> },
    { header: t("plans.price.interval"), cell: (p) => <span className="text-sm">{t(`interval.${p.interval}`)}</span> },
    { header: t("plans.price.amount"), align: "right", cell: (p) => <span className="text-sm">{p.withdrawn ? "-" : money(p.amount, p.currency)}{p.tax_inclusive && !p.withdrawn && <span className="ml-1 text-xs text-muted">{t("plans.price.taxIncl")}</span>}</span> },
    { header: t("plans.price.from"), cell: (p) => <span className="text-sm">{formatDate(p.effective_from, true)}</span> },
    { header: t("plans.price.state"), cell: (p) => { const s = priceState(p, currentIds); return <Badge tone={TONES[s]}>{t(`plans.price.states.${s}`)}</Badge>; } },
    { header: t("plans.price.by"), hideBelow: "md", cell: (p) => <span className="text-xs text-muted">{p.created_by ?? ""}</span> },
    {
      header: "", align: "right",
      cell: (p) => canEdit && p.id && priceState(p, currentIds) === "scheduled"
        ? <Button size="sm" variant="secondary" onClick={() => setRemoving(p)}>{t("plans.price.remove")}</Button> : null,
    },
  ];

  return (
    <div className="space-y-4">
      <DataTable rows={prices} columns={columns} rowKey={(p) => p.id ?? `${p.currency}-${p.interval}-${p.effective_from}`} dense pageSize={10} empty={{ title: t("plans.price.empty"), hint: t("plans.price.emptyHint") }} />

      {canEdit && (
        <form className="space-y-3 rounded-xl border border-line p-4" onSubmit={(e) => { e.preventDefault(); if (save.isPending) return; setProblem(null); if (Object.keys(errors).length > 0) { setShowErrors(true); return; } save.mutate(undefined); }}>
          <h3 className="text-sm font-semibold">{t("plans.price.addTitle")}</h3>
          <Alert tone="info">{t("plans.price.appendOnly")}</Alert>
          <FormGrid cols={3}>
            <Field label={t("plans.price.currency")} hint={t("plans.price.currencyHint")} error={showErrors && errors.currency ? t("plans.price.errors.currency") : null}>
              <Input value={form.currency} onChange={(e) => patch({ currency: e.target.value.toUpperCase() })} maxLength={3} className="font-mono uppercase" />
            </Field>
            <Field label={t("plans.price.interval")}>
              <Select value={form.interval} onChange={(e) => patch({ interval: e.target.value })}>{intervals.map((i) => <option key={i} value={i}>{t(`interval.${i}`)}</option>)}</Select>
            </Field>
            <Field label={t("plans.price.amount")} error={showErrors && errors.amount ? t("plans.price.errors.amount") : null}>
              <NumberInput value={form.withdrawn ? "" : form.amount} disabled={form.withdrawn} onChange={(v) => patch({ amount: v })} />
            </Field>
          </FormGrid>
          <FormGrid>
            <Field label={t("plans.price.effectiveFrom")} hint={t("plans.price.effectiveHint")}><Input type="date" value={form.effective_from} onChange={(e) => patch({ effective_from: e.target.value })} /></Field>
            <div className="space-y-2 sm:pt-6">
              <Checkbox label={t("plans.price.taxInclusive")} checked={form.tax_inclusive} onChange={(e) => patch({ tax_inclusive: e.target.checked })} />
              <Checkbox label={t("plans.price.withdrawn")} checked={form.withdrawn} onChange={(e) => patch({ withdrawn: e.target.checked })} />
            </div>
          </FormGrid>
          {problem && <Alert tone="bad">{problem}</Alert>}
          <div className="flex justify-end"><Button type="submit" loading={save.isPending}>{t("plans.price.add")}</Button></div>
        </form>
      )}

      {removing?.id && (
        <ChangeConfirm title={t("plans.price.removeTitle")} message={<p>{t("plans.price.removeMessage", { price: money(removing.amount, removing.currency), date: formatDate(removing.effective_from) })}</p>} confirmLabel={t("plans.price.remove")} danger
          run={() => remove(removing.id as string)} onDone={() => { toast(t("plans.price.removed"), "ok"); refresh(); }} onClose={() => setRemoving(null)} />
      )}
    </div>
  );
}

import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import {
  api, Button, Drawer, Field, FormGrid, IconButton, Input, NumberInput, orNull, Select, Switch, Textarea, toast, today, unwrap, useCompany, useCurrency, useFormState,
  useMutation, useQueryClient, useTranslation, money,
} from "@/sdk";

import { CustomerPicker, ServicePicker, useBranchChoice } from "../hooks";
import type { Schedule } from "../hooks";
import { type DraftLine, emptyLine, isLineComplete, linePreview, linesTotal } from "../logic";

function linesOf(schedule?: Schedule): DraftLine[] {
  return schedule ? schedule.lines.map((l) => ({ product_id: l.product_id, description: l.description ?? "", quantity: l.quantity, unit_price: l.unit_price, discount: l.discount })) : [emptyLine()];
}

/** Set up (or change what is invoiced by) a recurring invoice. The lines are what each period's invoice will contain. */
export function ScheduleForm({ open, onClose, schedule }: { open: boolean; onClose: () => void; schedule?: Schedule }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const editing = !!schedule;
  const f = useFormState({
    name: schedule?.name ?? "", billing_interval: schedule?.billing_interval ?? "month", interval_count: String(schedule?.interval_count ?? 1),
    anchor_day: schedule?.anchor_day ? String(schedule.anchor_day) : "", start_date: schedule?.start_date ?? today(), end_date: schedule?.end_date ?? "",
    max_runs: schedule?.max_runs ? String(schedule.max_runs) : "", due_days: schedule?.due_days != null ? String(schedule.due_days) : "", memo: schedule?.memo ?? "",
  });
  const [customer, setCustomer] = useState(schedule?.customer_id ?? "");
  const [branch, setBranch] = useState(schedule?.branch_id ?? "");
  const [draftOnly, setDraftOnly] = useState(schedule?.mode === "draft");
  const [lines, setLines] = useState<DraftLine[]>(linesOf(schedule));
  const { branchId, field: branchField } = useBranchChoice(company?.id ?? "", branch, setBranch);
  const { reset } = f;
  useEffect(() => {
    if (!open) return;
    reset(); setCustomer(schedule?.customer_id ?? ""); setBranch(schedule?.branch_id ?? ""); setDraftOnly(schedule?.mode === "draft"); setLines(linesOf(schedule));
  }, [open, schedule?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const setLine = (i: number, patch: Partial<DraftLine>) => setLines((all) => all.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  const complete = lines.filter(isLineComplete);
  const ready = (editing || !!customer) && f.values.name.trim() !== "" && complete.length > 0 && complete.length === lines.length;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const body = {
        name: v.name.trim(), lines: complete.map((l) => ({ product_id: l.product_id, description: orNull(l.description), quantity: l.quantity, unit_price: l.unit_price, discount: l.discount || "0" })),
        end_date: orNull(v.end_date), max_runs: v.max_runs ? Number(v.max_runs) : null, mode: (draftOnly ? "draft" : "issue") as "draft" | "issue",
        due_days: v.due_days ? Number(v.due_days) : null, memo: orNull(v.memo),
      };
      return schedule
        ? unwrap(api.PATCH("/api/v1/memberships/recurring-invoices/{schedule_id}", { params: { path: { schedule_id: schedule.id } }, body: { ...body, branch_id: branchId } }))
        : unwrap(api.POST("/api/v1/memberships/recurring-invoices", { body: {
            ...body, company_id: company?.id ?? "", branch_id: branchId, customer_id: customer, billing_interval: v.billing_interval as "month",
            interval_count: Number(v.interval_count) || 1, anchor_day: v.anchor_day ? Number(v.anchor_day) : null, start_date: v.start_date } }));
    },
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t(editing ? "scheduleSaved" : "scheduleCreated", { name: s.name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (ready) save.mutate(); };
  const monthly = f.values.billing_interval !== "week";

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("editSchedule") : t("newSchedule")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="schedule-form" loading={save.isPending} disabled={!ready}>{t("save")}</Button></>}>
      <form id="schedule-form" onSubmit={submit} className="space-y-4">
        {editing ? <p className="text-sm"><span className="text-muted">{t("customer")}: </span><span className="font-medium">{schedule.customer_name}</span></p>
          : <CustomerPicker value={customer} onChange={setCustomer} required error={f.error("customer_id")} />}
        <Field label={t("scheduleName")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={200} placeholder={t("scheduleNamePlaceholder")} /></Field>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("invoiceLines")}</p>
          {lines.map((l, i) => (
            <div key={i} className="space-y-2 rounded-md border border-line p-3">
              <ServicePicker value={l.product_id} onChange={(id) => setLine(i, { product_id: id })} label={t("item")} />
              <Field label={t("lineDescription")}><Input value={l.description} maxLength={300} onChange={(e) => setLine(i, { description: e.target.value })} placeholder={t("lineDescriptionPlaceholder")} /></Field>
              <FormGrid cols={3}>
                <Field label={t("quantity")}><NumberInput value={l.quantity} onChange={(v) => setLine(i, { quantity: v })} /></Field>
                <Field label={t("unitPrice")} hint={t("priceIncludesTax")}><NumberInput value={l.unit_price} onChange={(v) => setLine(i, { unit_price: v })} /></Field>
                <Field label={t("discount")}><NumberInput value={l.discount} onChange={(v) => setLine(i, { discount: v })} /></Field>
              </FormGrid>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted">{isLineComplete(l) ? money(linePreview(l.quantity, l.unit_price, l.discount), currency) : ""}</span>
                {lines.length > 1 && <IconButton label={t("removeLine")} onClick={() => setLines((all) => all.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></IconButton>}
              </div>
            </div>
          ))}
          <div className="flex items-center justify-between">
            <Button type="button" variant="secondary" size="sm" onClick={() => setLines((all) => [...all, emptyLine()])}><Plus className="h-4 w-4" />{t("addLine")}</Button>
            <span className="text-sm font-semibold">{t("eachInvoice", { total: money(linesTotal(lines), currency) })}</span>
          </div>
        </div>
        <FormGrid>
          <Field label={t("every")} error={f.error("interval_count")}><NumberInput value={f.values.interval_count} onChange={(v) => f.set("interval_count", v.split(".")[0] ?? "")} disabled={editing} /></Field>
          <Field label={t("period")} error={f.error("billing_interval")}>
            <Select {...f.bind("billing_interval")} disabled={editing}>{(["week", "month", "quarter", "year"] as const).map((i) => <option key={i} value={i}>{t(`unit.${i}`)}</option>)}</Select>
          </Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("firstInvoice")} error={f.error("start_date")}><Input type="date" {...f.bind("start_date")} disabled={editing} /></Field>
          {monthly && <Field label={t("dayOfMonth")} hint={t("dayOfMonthHint")} error={f.error("anchor_day")}><NumberInput value={f.values.anchor_day} disabled={editing} onChange={(v) => f.set("anchor_day", v.split(".")[0] ?? "")} /></Field>}
        </FormGrid>
        <FormGrid>
          <Field label={t("lastInvoiceOn")} hint={t("lastInvoiceOnHint")} error={f.error("end_date")}><Input type="date" {...f.bind("end_date")} /></Field>
          <Field label={t("orAfterCount")} hint={t("orAfterCountHint")} error={f.error("max_runs")}><NumberInput value={f.values.max_runs} onChange={(v) => f.set("max_runs", v.split(".")[0] ?? "")} /></Field>
        </FormGrid>
        <Switch checked={draftOnly} onChange={setDraftOnly} label={t("reviewFirst")} />
        <p className="-mt-2 text-xs text-muted">{t("reviewFirstHint")}</p>
        {branchField}
        <FormGrid>
          <Field label={t("dueInDays")} hint={t("dueInDaysHint")} error={f.error("due_days")}><NumberInput value={f.values.due_days} onChange={(v) => f.set("due_days", v.split(".")[0] ?? "")} /></Field>
        </FormGrid>
        <Field label={t("invoiceNote")} error={f.error("memo")}><Textarea rows={2} maxLength={300} {...f.bind("memo")} /></Field>
      </form>
    </Drawer>
  );
}

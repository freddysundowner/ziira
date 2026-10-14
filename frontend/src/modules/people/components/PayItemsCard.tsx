import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Badge, Button, Card, Checkbox, DataTable, Drawer, Field, formatDate, Input, Modal, money, NumberInput, Select, toast, today, unwrap, useFormState, useMutation,
  useQuery, useQueryClient, useTranslation, humanise,
} from "@/sdk";

import { usePayComponents } from "../lib/lookups";
import type { Employee, PayItem } from "../lib/types";

/** Recurring and one-off pay items: allowances, deductions, benefits in kind, employer extras. */
export function PayItemsCard({ employee, currency }: { employee: Employee; currency?: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<PayItem | null>(null);
  const components = usePayComponents(employee.company_id);
  const key = ["people", "pay-items", employee.id];
  const items = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/people/employees/{employee_id}/pay-items", { params: { path: { employee_id: employee.id } } })) });
  const component = (id: string) => components.data?.find((c) => c.id === id);

  return (
    <Card title={t("pay.items")} description={t("pay.itemsHint")} flush actions={<Button size="sm" onClick={() => setAdding(true)} disabled={(components.data ?? []).length === 0}><Plus className="h-3.5 w-3.5" />{t("pay.addItem")}</Button>}>
      {components.isSuccess && components.data.length === 0 && (
        <p className="border-b border-line px-4 py-3 text-sm text-muted">{t("pay.noComponents")} <Link className="font-medium text-brand underline" to="/pay-components">{t("pay.openSetup")}</Link></p>
      )}
      <DataTable
        rows={items.data} loading={items.isLoading} error={items.error?.message} onRetry={() => void items.refetch()} rowKey={(x) => x.id}
        empty={{ title: t("pay.noItems"), hint: t("pay.noItemsHint") }}
        columns={[
          { header: t("pay.component"), cell: (x) => <span className="font-medium">{component(x.component_id)?.name ?? "—"}{x.description && <span className="block text-xs font-normal text-muted">{x.description}</span>}</span> },
          { header: t("pay.kind"), hideBelow: "sm", cell: (x) => <Badge>{t(`component.kinds.${component(x.component_id)?.kind ?? ""}`, humanise(component(x.component_id)?.kind))}</Badge> },
          { header: t("amount"), align: "right", cell: (x) => money(x.amount, currency) },
          { header: t("pay.frequency"), hideBelow: "md", cell: (x) => (x.recurring ? t("pay.recurring") : t("pay.oneOff")) },
          { header: t("pay.validFrom"), hideBelow: "md", cell: (x) => formatDate(x.valid_from) },
          { header: t("pay.validTo"), hideBelow: "lg", cell: (x) => (x.valid_to ? formatDate(x.valid_to) : "—") },
          { header: "", align: "right", cell: (x) => x.recurring && !x.valid_to ? <Button size="sm" variant="secondary" onClick={() => setEnding(x)}>{t("pay.endItem")}</Button> : null },
        ]}
      />
      <AddItem open={adding} onClose={() => setAdding(false)} employee={employee} currency={currency} onSaved={() => void qc.invalidateQueries({ queryKey: key })} />
      <EndItem item={ending} onClose={() => setEnding(null)} onSaved={() => void qc.invalidateQueries({ queryKey: key })} />
    </Card>
  );
}

function AddItem({ open, onClose, employee, currency, onSaved }: { open: boolean; onClose: () => void; employee: Employee; currency?: string; onSaved: () => void }) {
  const { t } = useTranslation("people");
  const components = usePayComponents(employee.company_id, open);
  const f = useFormState({ component_id: "", amount: "", valid_from: today(), valid_to: "", description: "" });
  const [recurring, setRecurring] = useState(true);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/employees/{employee_id}/pay-items", { params: { path: { employee_id: employee.id } }, body: {
      component_id: f.values.component_id || components.data?.[0]?.id || "", amount: f.values.amount, valid_from: f.values.valid_from, recurring,
      valid_to: recurring && f.values.valid_to ? f.values.valid_to : null, description: f.values.description.trim() || null } })),
    onSuccess: () => { onSaved(); toast(t("pay.itemAdded"), "ok"); f.reset(); setRecurring(true); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("pay.addItem")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="item-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="item-form" onSubmit={submit} className="space-y-4">
        <Field label={t("pay.component")} required error={f.error("component_id")}>
          <Select {...f.bind("component_id")}>{(components.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} · {t(`component.kinds.${c.kind}`, humanise(c.kind))}</option>)}</Select>
        </Field>
        <Field label={`${t("amount")}${currency ? ` (${currency})` : ""}`} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
        <Checkbox label={t("pay.recurringCheck")} checked={recurring} onChange={(e) => setRecurring(e.target.checked)} />
        <Field label={recurring ? t("pay.validFrom") : t("pay.payOn")} required error={f.error("valid_from")}><Input type="date" {...f.bind("valid_from")} required /></Field>
        {recurring && <Field label={t("pay.validTo")} hint={t("pay.validToHint")} error={f.error("valid_to")}><Input type="date" {...f.bind("valid_to")} /></Field>}
        <Field label={t("pay.description")} error={f.error("description")}><Input {...f.bind("description")} maxLength={200} /></Field>
      </form>
    </Drawer>
  );
}

function EndItem({ item, onClose, onSaved }: { item: PayItem | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation("people");
  const [date, setDate] = useState(today());
  const end = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/people/pay-items/{item_id}/end", { params: { path: { item_id: item!.id } }, body: { valid_to: date } })),
    onSuccess: () => { onSaved(); toast(t("pay.itemEnded"), "ok"); onClose(); },
  });
  return (
    <Modal open={!!item} onClose={onClose} title={t("pay.endItem")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={end.isPending} disabled={!date} onClick={() => end.mutate()}>{t("pay.endItem")}</Button></>}>
      <Field label={t("pay.lastDay")} hint={t("pay.lastDayHint")}><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
    </Modal>
  );
}

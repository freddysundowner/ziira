import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api, Button, Checkbox, DataTable, Drawer, Field, Input, NumberInput, quantity, toast, unwrap, useCan, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import type { LeaveType } from "../lib/types";

export function TypesPanel({ companyId, types, loading, error, onRetry }: { companyId: string; types: LeaveType[] | undefined; loading: boolean; error?: string; onRetry: () => void }) {
  const { t } = useTranslation("people");
  const canManage = useCan("employees.manage");
  const [adding, setAdding] = useState(false);
  const add = canManage ? <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("leave.newType")}</Button> : undefined;
  return (
    <>
      <DataTable
        rows={types} loading={loading} error={error} onRetry={onRetry} rowKey={(x) => x.id} toolbar={add && <div className="ml-auto">{add}</div>}
        empty={{ title: t("leave.noTypes"), hint: t("leave.noTypesHint"), action: add }}
        columns={[
          { header: t("leave.type"), cell: (x) => <span className="font-medium">{x.name}</span> },
          { header: t("leave.entitled"), align: "right", cell: (x) => (x.days_per_year === null ? t("leave.unlimited") : quantity(x.days_per_year)) },
          { header: t("leave.paid"), cell: (x) => (x.is_paid ? t("yes") : t("leave.unpaid")) },
        ]}
      />
      {adding && <NewType onClose={() => setAdding(false)} companyId={companyId} />}
    </>
  );
}

function NewType({ onClose, companyId }: { onClose: () => void; companyId: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const f = useFormState({ name: "", days_per_year: "" });
  const [paid, setPaid] = useState(true);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/leave-types", { body: { company_id: companyId, name: f.values.name.trim(), days_per_year: f.values.days_per_year || null, is_paid: paid } })),
    onSuccess: (x) => { void qc.invalidateQueries({ queryKey: ["people", "leave-types"] }); toast(t("leave.typeCreated", { name: x.name }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("leave.newType")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="leave-type-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="leave-type-form" onSubmit={submit} className="space-y-4">
        <Field label={t("leave.typeName")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={60} /></Field>
        <Field label={t("leave.entitled")} hint={t("leave.entitledHint")} error={f.error("days_per_year")}><NumberInput value={f.values.days_per_year} onChange={(v) => f.set("days_per_year", v)} /></Field>
        <Checkbox label={t("leave.paidCheck")} checked={paid} onChange={(e) => setPaid(e.target.checked)} />
      </form>
    </Drawer>
  );
}

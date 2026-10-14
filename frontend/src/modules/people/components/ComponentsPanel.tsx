import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api, Badge, Button, Checkbox, DataTable, Drawer, Field, humanise, Input, Select, toast, unwrap, useCan, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { usePayComponents } from "../lib/lookups";

const KINDS = ["earning", "deduction", "benefit", "employer_contribution"] as const;

/** Pay components: the named kinds of pay item (allowances, loans, benefits in kind ...) that can be put on an employee. */
export function ComponentsPanel({ companyId }: { companyId: string }) {
  const { t } = useTranslation("people");
  const canEdit = useCan("employee.pay_edit");
  const [adding, setAdding] = useState(false);
  const components = usePayComponents(companyId);
  const add = canEdit ? <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("component.new")}</Button> : undefined;
  return (
    <>
      <p className="mb-3 max-w-2xl text-sm text-muted">{t("component.intro")}</p>
      <DataTable
        rows={components.data} loading={components.isLoading} error={components.error?.message} onRetry={() => void components.refetch()} rowKey={(c) => c.id}
        toolbar={add && <div className="ml-auto">{add}</div>}
        empty={{ title: t("component.empty"), hint: t("component.emptyHint"), action: add }}
        columns={[
          { header: t("component.code"), sortValue: (c) => c.code, cell: (c) => <span className="font-mono text-xs">{c.code}</span> },
          { header: t("component.name"), sortValue: (c) => c.name, cell: (c) => <span className="font-medium">{c.name}</span> },
          { header: t("pay.kind"), cell: (c) => <Badge>{t(`component.kinds.${c.kind}`, humanise(c.kind))}</Badge> },
          { header: t("component.taxable"), hideBelow: "sm", cell: (c) => (c.kind === "earning" ? (c.is_taxable ? t("yes") : t("no")) : "—") },
        ]}
      />
      {adding && <NewComponent onClose={() => setAdding(false)} companyId={companyId} />}
    </>
  );
}

function NewComponent({ onClose, companyId }: { onClose: () => void; companyId: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const f = useFormState({ code: "", name: "", kind: "earning" });
  const [taxable, setTaxable] = useState(true);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/pay-components", { body: { company_id: companyId, code: f.values.code.trim().toUpperCase(), name: f.values.name.trim(), kind: f.values.kind as "earning", is_taxable: taxable } })),
    onSuccess: (c) => { void qc.invalidateQueries({ queryKey: ["people", "components"] }); toast(t("component.created", { name: c.name }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("component.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="component-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="component-form" onSubmit={submit} className="space-y-4">
        <Field label={t("component.name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={100} /></Field>
        <Field label={t("component.code")} hint={t("component.codeHint")} required error={f.error("code")}><Input {...f.bind("code")} required maxLength={20} className="uppercase" /></Field>
        <Field label={t("pay.kind")} hint={t(`component.kindHint.${f.values.kind}`)}>
          <Select {...f.bind("kind")}>{KINDS.map((k) => <option key={k} value={k}>{t(`component.kinds.${k}`)}</option>)}</Select>
        </Field>
        {f.values.kind === "earning" && <Checkbox label={t("component.taxableCheck")} checked={taxable} onChange={(e) => setTaxable(e.target.checked)} />}
      </form>
    </Drawer>
  );
}

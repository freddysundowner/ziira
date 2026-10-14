import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Alert, Button, Checkbox, DataTable, Drawer, Field, FormGrid, humanise, Input, money, NumberInput, PageHeader, Select, StatusBadge, Switch,
  toast, unwrap, useCan, useCompany, useCurrency, useFormState, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { useSelectedCompany } from "../components/useSelectedCompany";

type Rule = Schemas["ziira__kernel__api__schemas__RuleOut"];

/** Who must approve what, by document type and amount range. */
export default function ApprovalRulesPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const canEdit = useCan("approvals.manage");
  const { companyId, picker } = useSelectedCompany(t("company"));
  const currency = useCurrency(companyId);
  const [creating, setCreating] = useState(false);
  const rules = useQuery({
    enabled: !!companyId, queryKey: ["approval-rules", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/approvals/rules", { params: { query: { company_id: companyId } } })),
  });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const toggle = useMutation({
    mutationFn: (r: Rule) => unwrap(api.POST("/api/v1/approvals/rules/{rule_id}/active", { params: { path: { rule_id: r.id } }, body: { active: !r.is_active } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["approval-rules"] }),
  });
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? "—";
  const range = (r: Rule) => (r.max_amount == null ? `${money(r.min_amount, currency)} +` : `${money(r.min_amount, currency)} – ${money(r.max_amount, currency)}`);

  return (
    <>
      <PageHeader title={t("approvalRules")} description={t("approvalRulesHint")}
        actions={canEdit && companyId ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newRule")}</Button> : undefined} />
      {picker && <div className="mb-4">{picker}</div>}
      <Alert className="mb-4">{t("rulesNote")}</Alert>
      <DataTable
        rows={rules.data} loading={rules.isLoading} error={rules.error?.message} onRetry={() => void rules.refetch()} rowKey={(r) => r.id}
        searchText={(r) => `${r.doc_type} ${roleName(r.approver_role_id)}`} searchPlaceholder={t("searchRules")} pageSize={20}
        empty={{ title: t("noRules"), hint: t("noRulesHint") }}
        columns={[
          { header: t("docType"), sortValue: (r) => r.doc_type, cell: (r) => <span className="font-medium">{humanise(r.doc_type)}</span> },
          { header: t("amountRange"), cell: range },
          { header: t("step"), hideBelow: "md", sortValue: (r) => r.step, cell: (r) => r.step },
          { header: t("approverRole"), hideBelow: "sm", cell: (r) => roleName(r.approver_role_id) },
          { header: t("forbidCreator"), hideBelow: "lg", cell: (r) => (r.forbid_creator ? t("yes") : t("no")) },
          { header: t("status"), hideBelow: "sm", cell: (r) => <StatusBadge status={r.is_active ? "active" : "inactive"} /> },
          {
            header: t("active"), align: "right",
            cell: (r) => <Switch label={`${t("active")}: ${humanise(r.doc_type)}`} checked={r.is_active} disabled={!canEdit || (toggle.isPending && toggle.variables?.id === r.id)} onChange={() => toggle.mutate(r)} />,
          },
        ]}
      />
      {companyId && <NewRule open={creating} companyId={companyId} currency={currency} onClose={() => setCreating(false)} />}
    </>
  );
}

function NewRule({ open, companyId, currency, onClose }: { open: boolean; companyId: string; currency?: string; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const { companies } = useCompany();
  const roles = useQuery({ enabled: open, queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const f = useFormState({ doc_type: "", approver_role_id: "", step: "1", min_amount: "0", max_amount: "" });
  const [forbidCreator, setForbidCreator] = useState(true);
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/approvals/rules", { body: {
      company_id: companyId, doc_type: f.values.doc_type.trim(), approver_role_id: f.values.approver_role_id, step: Number(f.values.step) || 1,
      min_amount: f.values.min_amount || "0", max_amount: f.values.max_amount || null, forbid_creator: forbidCreator,
    } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["approval-rules"] }); toast(t("ruleSaved"), "ok"); f.reset(); setForbidCreator(true); onClose(); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  const company = companies.find((c) => c.id === companyId);
  return (
    <Drawer open={open} onClose={onClose} title={t("newRule")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-rule" loading={create.isPending} disabled={!f.values.approver_role_id}>{t("save")}</Button></>}>
      <form id="new-rule" onSubmit={submit} className="space-y-4">
        {company && <p className="text-sm text-muted">{company.name}</p>}
        <Field label={t("docType")} hint={t("docTypeHint")} required error={f.error("doc_type")}><Input {...f.bind("doc_type")} required maxLength={60} /></Field>
        <Field label={t("approverRole")} required error={f.error("approver_role_id")}>
          <Select {...f.bind("approver_role_id")} required><option value="">{t("choose")}</option>{(roles.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>
        </Field>
        <FormGrid cols={3}>
          <Field label={t("step")} hint={t("stepHint")} error={f.error("step")}><NumberInput value={f.values.step} onChange={(v) => f.set("step", v)} /></Field>
          <Field label={`${t("minAmount")}${currency ? ` (${currency})` : ""}`} error={f.error("min_amount")}><NumberInput value={f.values.min_amount} onChange={(v) => f.set("min_amount", v)} /></Field>
          <Field label={`${t("maxAmount")}${currency ? ` (${currency})` : ""}`} hint={t("maxAmountHint")} error={f.error("max_amount")}><NumberInput value={f.values.max_amount} onChange={(v) => f.set("max_amount", v)} /></Field>
        </FormGrid>
        <Checkbox label={t("forbidCreatorLabel")} checked={forbidCreator} onChange={(e) => setForbidCreator(e.target.checked)} />
        
      </form>
    </Drawer>
  );
}

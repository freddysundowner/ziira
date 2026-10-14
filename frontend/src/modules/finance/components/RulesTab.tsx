import { Plus, X } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Combobox, ConfirmDialog, DataTable, Drawer, Field, FormGrid, humanise, IconButton, Input, Menu, NumberInput, Select, toast, unwrap, useCan,
  useFormState, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { accountNames, accountOptions, useAccounts } from "../api";

type Rule = Awaited<ReturnType<typeof fetchRules>>[number];
const fetchRules = (companyId: string) => unwrap(api.GET("/api/v1/finance/posting-rules", { params: { query: { company_id: companyId } } }));

/** Posting rules are data: which account a document line uses. A rule with conditions beats a general one. Changing one affects documents posted from now on. */
export function RulesTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const canManage = useCan("accounts.manage");
  const accounts = useAccounts(companyId, true);
  const names = accountNames(accounts.data);
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const rules = useQuery({ enabled: !!companyId, queryKey: ["finance", "rules", companyId], queryFn: () => fetchRules(companyId) });
  const remove = useMutation({
    mutationFn: (r: Rule) => unwrap(api.DELETE("/api/v1/finance/posting-rules/{posting_rule_id}", { params: { path: { posting_rule_id: r.id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["finance", "rules"] }); toast(t("rules.deleted"), "ok"); setDeleting(null); },
    onError: () => setDeleting(null),
  });
  const conditions = (r: Rule) => Object.entries(r.conditions).map(([k, v]) => `${humanise(k)}: ${v}`).join(", ");

  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("rules.hint")}</p>
      {canManage && <div className="mb-3 flex justify-end"><Button variant="secondary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("rules.new")}</Button></div>}
      <DataTable
        rows={rules.data} loading={rules.isLoading} error={rules.error?.message} onRetry={() => void rules.refetch()} rowKey={(r) => r.id} pageSize={50}
        searchText={(r) => `${r.doc_type} ${r.line_role} ${names.get(r.account_id) ?? ""}`} searchPlaceholder={t("rules.search")}
        empty={{ title: t("rules.empty"), hint: t("rules.emptyHint") }}
        columns={[
          { header: t("rules.document"), sortValue: (r) => r.doc_type, cell: (r) => <span className="font-medium">{humanise(r.doc_type)}</span> },
          { header: t("rules.role"), sortValue: (r) => r.line_role, cell: (r) => humanise(r.line_role) },
          { header: t("rules.side"), hideBelow: "sm", cell: (r) => <Badge tone={r.side === "debit" ? "info" : "brand"}>{t(r.side === "debit" ? "debit" : "credit")}</Badge> },
          { header: t("rules.when"), hideBelow: "lg", cell: (r) => conditions(r) || <span className="text-muted">{t("rules.always")}</span> },
          { header: t("account"), cell: (r) => names.get(r.account_id) ?? "…" },
          {
            header: "", align: "right", cell: (r) => canManage && (
              <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                { label: t("rules.changeAccount"), onSelect: () => setEditing(r) },
                { label: t("delete"), danger: true, onSelect: () => setDeleting(r) },
              ]} />),
          },
        ]}
      />
      <RuleDrawer target={editing} onClose={() => setEditing(null)} companyId={companyId} />
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} busy={remove.isPending} danger title={t("rules.deleteTitle")} confirmLabel={t("delete")}
        message={t("rules.deleteAsk")} onConfirm={() => deleting && remove.mutate(deleting)} />
    </>
  );
}

function RuleDrawer({ target, onClose, companyId }: { target: Rule | "new" | null; onClose: () => void; companyId: string }) {
  if (!target) return null;
  return <RuleForm key={target === "new" ? "new" : target.id} rule={target === "new" ? undefined : target} onClose={onClose} companyId={companyId} />;
}

function RuleForm({ rule, onClose, companyId }: { rule?: Rule; onClose: () => void; companyId: string }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const accounts = useAccounts(companyId);
  const f = useFormState({ doc_type: "", line_role: "", side: "debit", account_id: rule?.account_id ?? "", priority: "100" });
  const [conds, setConds] = useState<{ key: string; value: string }[]>([]);
  const done = () => { void qc.invalidateQueries({ queryKey: ["finance", "rules"] }); toast(t("rules.saved"), "ok"); onClose(); };
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => rule
      ? unwrap(api.PUT("/api/v1/finance/posting-rules/{posting_rule_id}", { params: { path: { posting_rule_id: rule.id } }, body: { account_id: f.values.account_id } }))
      : unwrap(api.POST("/api/v1/finance/posting-rules", { body: {
        company_id: companyId, doc_type: f.values.doc_type.trim(), line_role: f.values.line_role.trim(), account_id: f.values.account_id, side: f.values.side as "debit",
        priority: Number(f.values.priority) || 100, conditions: Object.fromEntries(conds.filter((c) => c.key.trim()).map((c) => [c.key.trim(), c.value.trim()])) } })),
    onSuccess: done,
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  return (
    <Drawer open onClose={onClose} title={rule ? `${humanise(rule.doc_type)} · ${humanise(rule.line_role)}` : t("rules.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="rule-form" loading={save.isPending} disabled={!f.values.account_id}>{t("save")}</Button></>}>
      <form id="rule-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {!rule && (
          <>
            <FormGrid>
              <Field label={t("rules.document")} required error={f.error("doc_type")} hint={t("rules.documentHint")}><Input {...f.bind("doc_type")} required maxLength={40} autoFocus /></Field>
              <Field label={t("rules.role")} required error={f.error("line_role")} hint={t("rules.roleHint")}><Input {...f.bind("line_role")} required maxLength={40} /></Field>
              <Field label={t("rules.side")}><Select {...f.bind("side")}><option value="debit">{t("debit")}</option><option value="credit">{t("credit")}</option></Select></Field>
              <Field label={t("rules.priority")} hint={t("rules.priorityHint")} error={f.error("priority")}><NumberInput value={f.values.priority} onChange={(v) => f.set("priority", v)} /></Field>
            </FormGrid>
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("rules.when")}</p>
              <p className="text-xs text-muted">{t("rules.whenHint")}</p>
              {conds.map((c, i) => (
                <div key={i} className="flex gap-2">
                  <Input aria-label={t("rules.conditionName")} placeholder={t("rules.conditionName")} value={c.key} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
                  <Input aria-label={t("rules.conditionValue")} placeholder={t("rules.conditionValue")} value={c.value} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  <IconButton label={t("removeLine")} onClick={() => setConds(conds.filter((_, j) => j !== i))}><X className="h-4 w-4" /></IconButton>
                </div>
              ))}
              <Button variant="ghost" size="sm" onClick={() => setConds([...conds, { key: "", value: "" }])}><Plus className="h-4 w-4" />{t("rules.addCondition")}</Button>
            </div>
          </>
        )}
        <Field label={t("account")} required error={f.error("account_id")} hint={rule ? t("rules.changeHint") : undefined}>
          <Combobox value={f.values.account_id} onChange={(v) => f.set("account_id", v)} options={accountOptions(accounts.data)} placeholder={t("chooseAccount")} />
        </Field>
      </form>
    </Drawer>
  );
}

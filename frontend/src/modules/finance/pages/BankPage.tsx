import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Button, Combobox, DataTable, Drawer, Field, FormGrid, formatDate, humanise, Input, money, PageHeader, Pager, Select, StatusBadge, toast, today, unwrap, useCan,
  useFormState, useMutation, usePagedList, useQueryClient, useTranslation,
} from "@/sdk";
import { useNavigate } from "react-router-dom";

import { accountNames, accountOptions, useAccounts } from "../api";
import { isSignedAmount } from "../lib";
import { ScopeSelects, type Scope, useScope } from "../scope";

/** Bank, mobile money and card reconciliations: start one against a statement, continue one in progress, or look back at finished ones. */
export default function BankPage() {
  const { t } = useTranslation("finance");
  const scope = useScope();
  const canReconcile = useCan("bank.reconcile");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const accounts = useAccounts(scope.companyId, true);
  const names = accountNames(accounts.data);
  const list = usePagedList(["finance", "recons", scope.companyId, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/finance/bank-reconciliations", { params: { query: { company_id: scope.companyId || undefined, status: (status || undefined) as "completed" | undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("bank.title")} description={t("bank.hint")}
        actions={<><ScopeSelects scope={scope} branch={false} />{canReconcile && <Button onClick={() => setCreating(true)} disabled={!scope.companyId}><Plus className="h-4 w-4" />{t("bank.start")}</Button>}</>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        rowHref={(r) => `/finance/bank/${r.id}`}
        toolbar={
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("allStatuses")}</option>
            <option value="in_progress">{humanise("in_progress")}</option>
            <option value="completed">{humanise("completed")}</option>
          </Select>}
        empty={{ title: t("bank.empty"), hint: t("bank.emptyHint"), action: canReconcile ? <Button onClick={() => setCreating(true)}>{t("bank.start")}</Button> : undefined }}
        columns={[
          { header: t("account"), cell: (r) => <span className="font-medium">{r.account_id ? names.get(r.account_id) ?? "…" : "—"}</span> },
          { header: t("bank.statementDate"), sortValue: (r) => r.statement_date, cell: (r) => formatDate(r.statement_date) },
          { header: t("bank.statementBalance"), align: "right", hideBelow: "sm", cell: (r) => money(r.statement_balance, scope.currency) },
          { header: t("bank.difference"), align: "right", cell: (r) => <span className={Number(r.difference) === 0 ? "text-ok" : "text-bad"}>{money(r.difference, scope.currency)}</span> },
          { header: t("status"), cell: (r) => <StatusBadge status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <StartDrawer open={creating} onClose={() => setCreating(false)} scope={scope} />
    </>
  );
}

function StartDrawer({ open, onClose, scope }: { open: boolean; onClose: () => void; scope: Scope }) {
  if (!open) return null;
  return <StartForm onClose={onClose} scope={scope} />;
}

function StartForm({ onClose, scope }: { onClose: () => void; scope: Scope }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const accounts = useAccounts(scope.companyId);
  const f = useFormState({ account_id: "", statement_date: today(), statement_balance: "" });
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/finance/bank-reconciliations", { body: {
      company_id: scope.companyId, account_id: f.values.account_id, statement_date: f.values.statement_date, statement_balance: f.values.statement_balance.trim() } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["finance", "recons"] }); onClose(); navigate(`/finance/bank/${r.id}`); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const valid = !!f.values.account_id && !!f.values.statement_date && isSignedAmount(f.values.statement_balance);
  return (
    <Drawer open onClose={onClose} title={t("bank.start")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="recon-form" loading={start.isPending} disabled={!valid}>{t("bank.startNow")}</Button></>}>
      <form id="recon-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) start.mutate(); }}>
        <p className="text-sm text-muted">{t("bank.startHint")}</p>
        <Field label={t("account")} required error={f.error("account_id")} hint={t("bank.accountHint")}>
          <Combobox value={f.values.account_id} onChange={(v) => f.set("account_id", v)} options={accountOptions(accounts.data, { types: ["asset"] })} placeholder={t("chooseAccount")} />
        </Field>
        <FormGrid>
          <Field label={t("bank.statementDate")} required error={f.error("statement_date")}><Input type="date" {...f.bind("statement_date")} required /></Field>
          <Field label={t("bank.statementBalance")} required error={f.error("statement_balance")} hint={t("bank.balanceHint")}>
            <Input inputMode="decimal" className="tnum text-right" value={f.values.statement_balance} placeholder="0.00" onChange={(e) => f.set("statement_balance", e.target.value.replace(/,/g, "."))} required />
          </Field>
        </FormGrid>
      </form>
    </Drawer>
  );
}

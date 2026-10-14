import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, DataTable, formatDate, humanise, Input, money, PageHeader, Pager, Select, StatusBadge, unwrap, useCan, usePagedList, useTranslation } from "@/sdk";

import { accountNames, useAccounts } from "../api";
import { ExpenseDrawer } from "../components/ExpenseDrawer";
import { ScopeSelects, useScope } from "../scope";

const EXPENSE_STATUSES = ["draft", "pending_approval", "posted", "rejected", "reversed"] as const;

/** Costs paid at once from cash, bank, mobile money or card. Each is a draft, then submitted (posts at once or waits for an approver). */
export default function ExpensesPage() {
  const { t } = useTranslation("finance");
  const scope = useScope();
  const canSubmit = useCan("expenses.submit");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const accounts = useAccounts(scope.companyId, true);
  const names = accountNames(accounts.data);
  const list = usePagedList(["finance", "expenses", scope.companyId, status, from, to], (limit, offset) =>
    unwrap(api.GET("/api/v1/finance/expenses", { params: { query: { company_id: scope.companyId || undefined, status: status || undefined, date_from: from || undefined, date_to: to || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("expenses.title")} description={t("expenses.hint")}
        actions={<><ScopeSelects scope={scope} branch={false} />{canSubmit && <Button onClick={() => setCreating(true)} disabled={!scope.companyId}><Plus className="h-4 w-4" />{t("expenses.new")}</Button>}</>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(x) => x.id}
        rowHref={(x) => `/finance/expenses/${x.id}`} searchText={(x) => `${x.number} ${x.description} ${x.payee ?? ""} ${names.get(x.account_id) ?? ""}`} searchPlaceholder={t("expenses.search")}
        toolbar={<>
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("allStatuses")}</option>
            {EXPENSE_STATUSES.map((s) => <option key={s} value={s}>{humanise(s)}</option>)}
          </Select>
          <Input type="date" aria-label={t("from")} className="w-auto" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
          <Input type="date" aria-label={t("to")} className="w-auto" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </>}
        empty={{ title: t("expenses.empty"), hint: t("expenses.emptyHint"), action: canSubmit ? <Button onClick={() => setCreating(true)}>{t("expenses.new")}</Button> : undefined }}
        columns={[
          { header: t("number"), cell: (x) => <span className="font-mono text-xs font-medium">{x.number}</span> },
          { header: t("date"), sortValue: (x) => x.expense_date, cell: (x) => formatDate(x.expense_date) },
          { header: t("description"), cell: (x) => <span className="font-medium">{x.description}</span> },
          { header: t("expenses.category"), hideBelow: "md", cell: (x) => names.get(x.account_id) ?? "…" },
          { header: t("expenses.payee"), hideBelow: "lg", cell: (x) => x.payee ?? "—" },
          { header: t("amount"), align: "right", sortValue: (x) => Number(x.amount), cell: (x) => money(x.amount, scope.companies.find((c) => c.id === x.company_id)?.currency ?? scope.currency) },
          { header: t("status"), cell: (x) => <StatusBadge status={x.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <ExpenseDrawer open={creating} onClose={() => setCreating(false)} scope={scope} />
    </>
  );
}

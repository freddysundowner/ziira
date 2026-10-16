import { Plus, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Button, Checkbox, DataTable, formatDate, Input, PageHeader, Pager, Select, today, unwrap, useCan, useDebounced, usePagedList, useTranslation,
} from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { CustomerName, CustomerPicker } from "./hooks";
import { dayBefore, invoiceDisplayStatus, outstanding } from "./lib";

const STATUSES = ["issued", "part_paid", "paid", "cancelled"] as const;
const OPEN = ["issued", "part_paid"];

/** Customer invoices: filter by status, customer, number or overdue. */
export default function InvoicesPage() {
  const { t } = useTranslation("pos");
  const canManage = useCan("invoices.manage");
  const [customer, setCustomer] = useState("");
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [search, setSearch] = useState("");
  const number = useDebounced(search.trim());
  const { nameOf, branches } = useBranches();
  const m = useMoney();
  const now = today();

  const list = usePagedList(["pos-docs", "invoices", customer, status, overdue, number], async (limit, offset) => {
    const rows = await unwrap(api.GET("/api/v1/pos/invoices", { params: { query: {
      customer_id: customer || undefined, status: status || undefined, number: number || undefined,
      due_before: overdue ? dayBefore(now) : undefined, limit, offset } } }));
    // the server filters by due date only: keep the ones still owing (a page can come back shorter)
    return overdue ? rows.filter((i) => OPEN.includes(i.status)) : rows;
  });
  const filtered = Boolean(customer || status || overdue || number);

  return (
    <>
      <PageHeader title={t("docs.tabs.invoices")} description={t("docs.hint.invoice")}
        actions={canManage && <Link to="/pos/invoices/new"><Button><Plus className="h-4 w-4" />{t("docs.new.invoice")}</Button></Link>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(i) => i.id} rowHref={(i) => `/pos/invoices/${i.id}`}
        toolbar={(
          <>
            <Input className="w-44" aria-label={t("docs.invoiceNumber")} placeholder={t("docs.invoiceNumber")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="w-56"><CustomerPicker value={customer} onChange={setCustomer} clearable placeholder={t("docs.allCustomers")} /></div>
            <Select className="w-40" aria-label={t("status")} value={status} disabled={overdue} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`docs.status.${s}`)}</option>)}
            </Select>
            <Checkbox label={t("docs.overdueOnly")} checked={overdue} onChange={(e) => { setOverdue(e.target.checked); setStatus(""); }} />
            {filtered && <Button variant="ghost" onClick={() => { setCustomer(""); setStatus(""); setOverdue(false); setSearch(""); }}><X className="h-4 w-4" />{t("clearFilters")}</Button>}
          </>
        )}
        empty={{ title: filtered ? t("docs.noMatch.invoice") : t("docs.none.invoice"), hint: filtered ? t("tryOtherFilters") : t("docs.noneHint.invoice") }}
        columns={[
          { header: t("number"), cell: (i) => <span className="font-mono text-xs font-medium">{i.number}</span> },
          { header: t("docs.customer"), cell: (i) => <CustomerName id={i.customer_id} /> },
          { header: t("docs.issued"), hideBelow: "md", cell: (i) => formatDate(i.issue_date) },
          { header: t("docs.dueDate"), hideBelow: "sm", cell: (i) => formatDate(i.due_date) },
          ...(branches.length > 1 ? [{ header: t("branch"), hideBelow: "lg" as const, cell: (i: { branch_id: string | null }) => nameOf(i.branch_id) }] : []),
          { header: t("total"), align: "right", cell: (i) => m(i.total, i.company_id) },
          { header: t("docs.owed"), align: "right", hideBelow: "md", cell: (i) => m(outstanding(i), i.company_id) },
          { header: t("status"), cell: (i) => <DocStatus status={invoiceDisplayStatus(i, now)} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}

import { Plus, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Button, DataTable, formatDate, PageHeader, Pager, Select, unwrap, useCan, usePagedList, useTranslation } from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { DocsTabs } from "./DocsTabs";
import { CustomerName, CustomerPicker } from "./hooks";

const STATUSES = {
  quotation: ["draft", "sent", "confirmed", "expired", "cancelled"],
  order: ["draft", "pending_approval", "confirmed", "fulfilled", "cancelled"],
} as const;

/** Quotations or sales orders, newest first, filtered by customer and status. */
export function DocListPage({ kind }: { kind: "quotation" | "order" }) {
  const { t } = useTranslation("pos");
  const canManage = useCan("invoices.manage");
  const [customer, setCustomer] = useState("");
  const [status, setStatus] = useState("");
  const { nameOf, branches } = useBranches();
  const m = useMoney();
  const list = usePagedList(["pos-docs", kind, customer, status], (limit, offset) => {
    const query = { customer_id: customer || undefined, status: status || undefined, limit, offset };
    return unwrap(kind === "quotation" ? api.GET("/api/v1/pos/quotations", { params: { query } }) : api.GET("/api/v1/pos/orders", { params: { query } }));
  });
  const filtered = Boolean(customer || status);
  const base = kind === "quotation" ? "/pos/quotations" : "/pos/orders";

  return (
    <>
      <PageHeader title={t("docs.title")} description={t(`docs.hint.${kind}`)}
        actions={canManage && <Link to={`${base}/new`}><Button><Plus className="h-4 w-4" />{t(`docs.new.${kind}`)}</Button></Link>} />
      <DocsTabs />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(d) => d.id} rowHref={(d) => `${base}/${d.id}`}
        toolbar={(
          <>
            <div className="w-56"><CustomerPicker value={customer} onChange={setCustomer} clearable placeholder={t("docs.allCustomers")} /></div>
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUSES[kind].map((s) => <option key={s} value={s}>{t(`docs.status.${s}`)}</option>)}
            </Select>
            {filtered && <Button variant="ghost" onClick={() => { setCustomer(""); setStatus(""); }}><X className="h-4 w-4" />{t("clearFilters")}</Button>}
          </>
        )}
        empty={{
          title: filtered ? t(`docs.noMatch.${kind}`) : t(`docs.none.${kind}`),
          hint: filtered ? t("tryOtherFilters") : t(`docs.noneHint.${kind}`),
        }}
        columns={[
          { header: t("number"), cell: (d) => <span className="font-mono text-xs font-medium">{d.number}</span> },
          { header: t("docs.customer"), cell: (d) => <CustomerName id={d.customer_id} /> },
          { header: t("docs.date"), hideBelow: "sm", cell: (d) => formatDate(d.doc_date) },
          ...(kind === "quotation" ? [{ header: t("docs.validUntil"), hideBelow: "md" as const, cell: (d: { valid_until: string | null }) => (d.valid_until ? formatDate(d.valid_until) : "—") }] : []),
          ...(branches.length > 1 ? [{ header: t("branch"), hideBelow: "lg" as const, cell: (d: { branch_id: string | null }) => nameOf(d.branch_id) }] : []),
          { header: t("total"), align: "right", cell: (d) => m(d.total, d.company_id) },
          { header: t("status"), cell: (d) => <DocStatus status={d.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}

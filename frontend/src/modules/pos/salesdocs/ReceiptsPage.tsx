import { X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, Button, DataTable, formatDate, humanise, PageHeader, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { CustomerName, CustomerPicker } from "./hooks";
import { isPositive } from "./lib";
import { ReceiptDetail } from "./ReceiptDetail";

/** Money received from customers (payments on invoices and advances). Open one to print, reverse, apply or give back. */
export default function ReceiptsPage() {
  const { t } = useTranslation("pos");
  const [params, setParams] = useSearchParams();
  const open = params.get("open");
  const [customer, setCustomer] = useState("");
  const { nameOf, branches } = useBranches();
  const m = useMoney();
  const list = usePagedList(["pos-docs", "receipts", customer], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/receipts", { params: { query: { customer_id: customer || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("docs.tabs.customerPayments")} description={t("docs.hint.receipt")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(r) => r.id} rowHref={(r) => `/pos/receipts?open=${r.id}`}
        toolbar={(
          <>
            <div className="w-56"><CustomerPicker value={customer} onChange={setCustomer} clearable placeholder={t("docs.allCustomers")} /></div>
            {customer && <Button variant="ghost" onClick={() => setCustomer("")}><X className="h-4 w-4" />{t("clearFilters")}</Button>}
          </>
        )}
        empty={{ title: customer ? t("docs.noMatch.receipt") : t("docs.none.receipt"), hint: customer ? t("tryOtherFilters") : t("docs.noneHint.receipt") }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("docs.customer"), cell: (r) => <CustomerName id={r.customer_id} /> },
          { header: t("docs.receivedOn"), hideBelow: "sm", cell: (r) => formatDate(r.received_on) },
          { header: t("method"), hideBelow: "md", cell: (r) => t(`docs.payVia.${r.method}`, humanise(r.method)) },
          { header: t("reference"), hideBelow: "lg", cell: (r) => r.reference ?? "—" },
          ...(branches.length > 1 ? [{ header: t("branch"), hideBelow: "lg" as const, cell: (r: { branch_id: string | null }) => nameOf(r.branch_id) }] : []),
          { header: t("amount"), align: "right", cell: (r) => m(r.amount, r.company_id) },
          { header: t("docs.heldOnAccount"), align: "right", hideBelow: "md", cell: (r) => (isPositive(r.unallocated) ? m(r.unallocated, r.company_id) : "—") },
          { header: t("status"), cell: (r) => <DocStatus status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {open && <ReceiptDetail receiptId={open} onClose={() => setParams({}, { replace: true })} />}
    </>
  );
}

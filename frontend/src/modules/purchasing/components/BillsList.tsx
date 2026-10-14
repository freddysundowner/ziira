import { useState } from "react";

import { api, Checkbox, DataTable, formatDate, Input, Pager, Select, today, unwrap, useDebounced, usePagedList, useTranslation } from "@/sdk";

import { amountDue, BILL_STATUSES, isOverdue } from "../lib";
import { SupplierName } from "./names";
import { Money } from "./Money";
import { Status } from "./Status";

/** Supplier bills, server-paged, with a status filter and an "overdue" switch. Pass `supplierId` to show one supplier's bills. */
export function BillsList({ supplierId }: { supplierId?: string }) {
  const { t } = useTranslation("purchasing");
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [text, setText] = useState("");
  const q = useDebounced(text.trim().toLowerCase());
  const day = today();
  const list = usePagedList(["purchasing", "bills", supplierId, status, overdue], (limit, offset) =>
    unwrap(api.GET("/api/v1/purchasing/bills", { params: { query: { supplier_id: supplierId, status: status || undefined, due_before: overdue ? day : undefined, limit, offset } } })));
  const rows = q ? list.rows?.filter((b) => `${b.number} ${b.supplier_invoice_no}`.toLowerCase().includes(q)) : list.rows;

  return (
    <DataTable
      rows={rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(b) => b.id} rowHref={(b) => `/bills/${b.id}`}
      toolbar={<>
        <Input className="max-w-xs" aria-label={t("findOnPage")} placeholder={t("findBill")} value={text} onChange={(e) => setText(e.target.value)} />
        <Select className="w-48" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("allStatuses")}</option>
          {BILL_STATUSES.map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}
        </Select>
        <Checkbox label={t("overdueOnly")} checked={overdue} onChange={(e) => setOverdue(e.target.checked)} />
      </>}
      empty={{ title: status || overdue ? t("noBillMatch") : t("noBills"), hint: status || overdue ? undefined : t("noBillsHint") }}
      columns={[
        { header: t("number"), sortValue: (b) => b.number, cell: (b) => <span className="font-mono text-xs font-medium">{b.number}</span> },
        { header: t("theirInvoice"), cell: (b) => b.supplier_invoice_no },
        ...(supplierId ? [] : [{ header: t("supplier"), hideBelow: "sm" as const, cell: (b: { supplier_id: string }) => <SupplierName id={b.supplier_id} /> }]),
        { header: t("billDate"), hideBelow: "lg", sortValue: (b) => b.bill_date, cell: (b) => formatDate(b.bill_date) },
        { header: t("dueDate"), hideBelow: "md", sortValue: (b) => b.due_date, cell: (b) => <span className={isOverdue(b, day) ? "font-medium text-bad" : ""}>{formatDate(b.due_date)}</span> },
        { header: t("total"), align: "right", cell: (b) => <Money value={b.total} companyId={b.company_id} /> },
        { header: t("stillOwed"), hideBelow: "md", align: "right", cell: (b) => (["posted", "part_paid"].includes(b.status) ? <Money value={amountDue(b)} companyId={b.company_id} /> : "—") },
        { header: t("status"), cell: (b) => <Status status={b.status} /> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}

import { useState } from "react";

import { api, DataTable, formatDate, Pager, Select, unwrap, usePagedList, useTranslation } from "@/sdk";

import { ORDER_STATUSES } from "../lib";
import { SupplierName } from "./names";
import { Money } from "./Money";
import { Status } from "./Status";

/** Purchase orders, server-paged, with a status filter. Pass `supplierId` to show one supplier's orders. */
export function OrdersList({ supplierId }: { supplierId?: string }) {
  const { t } = useTranslation("purchasing");
  const [status, setStatus] = useState("");
  const list = usePagedList(["purchasing", "orders", supplierId, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/purchasing/orders", { params: { query: { supplier_id: supplierId, status: status || undefined, limit, offset } } })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(o) => o.id} rowHref={(o) => `/orders/${o.id}`}
      toolbar={
        <Select className="w-52" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("allStatuses")}</option>
          {ORDER_STATUSES.map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}
        </Select>}
      empty={{ title: status ? t("noOrderMatch") : t("noOrders"), hint: status ? undefined : t("noOrdersHint") }}
      columns={[
        { header: t("number"), sortValue: (o) => o.number, cell: (o) => <span className="font-mono text-xs font-medium">{o.number}</span> },
        ...(supplierId ? [] : [{ header: t("supplier"), cell: (o: { supplier_id: string }) => <SupplierName id={o.supplier_id} /> }]),
        { header: t("orderDate"), hideBelow: "sm", sortValue: (o) => o.order_date, cell: (o) => formatDate(o.order_date) },
        { header: t("expectedDate"), hideBelow: "md", cell: (o) => formatDate(o.expected_date) },
        { header: t("total"), align: "right", cell: (o) => <Money value={o.total} companyId={o.company_id} /> },
        { header: t("status"), cell: (o) => <Status status={o.status} /> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}

import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { api, Button, DataTable, formatDate, PageHeader, Pager, unwrap, useCan, usePagedList, useTranslation } from "@/sdk";

import { Money } from "../components/Money";
import { SupplierName } from "../components/names";
import { Status } from "../components/Status";

export default function ReceiptsPage() {
  const { t } = useTranslation("purchasing");
  const canReceive = useCan("goods.receive");
  const list = usePagedList(["purchasing", "receipts"], (limit, offset) => unwrap(api.GET("/api/v1/purchasing/receipts", { params: { query: { limit, offset } } })));
  return (
    <>
      <PageHeader title={t("receipts")} description={t("receiptsHint")} actions={canReceive && <Link to="/receipts/new"><Button><Plus className="h-4 w-4" />{t("newReceipt")}</Button></Link>} />
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id} rowHref={(r) => `/receipts/${r.id}`}
        empty={{ title: t("noReceipts"), hint: t("noReceiptsHint") }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("supplier"), cell: (r) => <SupplierName id={r.supplier_id} /> },
          { header: t("receivedOn"), hideBelow: "sm", sortValue: (r) => r.received_at, cell: (r) => formatDate(r.received_at, true) },
          { header: t("deliveryNote"), hideBelow: "md", cell: (r) => r.delivery_note_no ?? "—" },
          { header: t("landedCost"), hideBelow: "lg", align: "right", cell: (r) => (Number(r.landed_cost) > 0 ? <Money value={r.landed_cost} companyId={r.company_id} /> : "—") },
          { header: t("status"), cell: (r) => <Status status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </>
  );
}

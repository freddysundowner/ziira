import { Link, useParams } from "react-router-dom";

import { Alert, api, Card, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { Money } from "../components/Money";
import { ProductName, SupplierName } from "../components/names";

export default function ReturnPage() {
  const { t } = useTranslation("purchasing");
  const { returnId = "" } = useParams();
  const ret = useQuery({ queryKey: ["purchasing", "return", returnId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/returns/{return_id}", { params: { path: { return_id: returnId } } })) });
  const r = ret.data;
  if (ret.error) return <ErrorState title={t("returnNotFound")} message={ret.error.message} onRetry={() => void ret.refetch()} />;
  if (!r) return <Skeleton className="h-40 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/returns", label: t("returns") }} title={t("returnTitle", { number: r.number })} description={<SupplierName id={r.supplier_id} link />} />
      <div className="space-y-4">
        <Alert tone="info">{t("creditAfterReturn")}</Alert>
        <Card>
          <DetailList items={[
            { label: t("supplier"), value: <SupplierName id={r.supplier_id} link /> },
            { label: t("date"), value: formatDate(r.returned_at, true) },
            { label: t("receipt"), value: <Link className="font-medium text-brand-strong hover:underline" to={`/receipts/${r.receipt_id}`}>{t("openReceipt")}</Link> },
            { label: t("note"), value: r.note },
          ]} />
        </Card>
        <Card title={t("goodsReturned")} flush>
          <DataTable rows={r.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
              { header: t("returnQty"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("unitCost"), align: "right", hideBelow: "sm", cell: (l) => <Money value={l.unit_cost} companyId={r.company_id} /> },
              { header: t("stockValue"), align: "right", hideBelow: "md", cell: (l) => <Money value={l.stock_value} companyId={r.company_id} /> },
              { header: t("qtyCredited"), align: "right", cell: (l) => quantity(l.qty_credited) },
            ]} />
        </Card>
      </div>
    </>
  );
}

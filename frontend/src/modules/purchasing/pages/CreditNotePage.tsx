import { Link, useParams } from "react-router-dom";

import { api, Card, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Skeleton, unwrap, useCurrency, useQuery, useTranslation } from "@/sdk";

import { Money } from "../components/Money";
import { SupplierName } from "../components/names";
import { Totals } from "../components/Totals";

export default function CreditNotePage() {
  const { t } = useTranslation("purchasing");
  const { noteId = "" } = useParams();
  const note = useQuery({ queryKey: ["purchasing", "credit-note", noteId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/credit-notes/{note_id}", { params: { path: { note_id: noteId } } })) });
  const c = note.data;
  const currency = useCurrency(c?.company_id);
  if (note.error) return <ErrorState title={t("creditNoteNotFound")} message={note.error.message} onRetry={() => void note.refetch()} />;
  if (!c) return <Skeleton className="h-40 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/credit-notes", label: t("creditNotes") }} title={t("creditNoteTitle", { number: c.number })} description={<SupplierName id={c.supplier_id} link />} />
      <div className="space-y-4">
        <Card>
          <DetailList items={[
            { label: t("supplier"), value: <SupplierName id={c.supplier_id} link /> },
            { label: t("theirCreditNo"), value: c.supplier_credit_no },
            { label: t("date"), value: formatDate(c.credit_date) },
            { label: t("bill"), value: <Link className="font-medium text-brand hover:underline" to={`/bills/${c.bill_id}`}>{t("openBill")}</Link> },
          ]} />
        </Card>
        <Card title={t("lines")} flush>
          <DataTable rows={c.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("description"), cell: (l) => l.description ?? (l.return_line_id ? t("goodsReturned") : "—") },
              { header: t("quantity"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("unitCostBeforeTax"), align: "right", hideBelow: "sm", cell: (l) => <Money value={l.unit_cost} companyId={c.company_id} /> },
              { header: t("tax"), align: "right", hideBelow: "md", cell: (l) => <Money value={l.tax_amount} companyId={c.company_id} /> },
              { header: t("lineTotal"), align: "right", cell: (l) => <Money value={l.line_total} companyId={c.company_id} /> },
            ]} />
          <div className="border-t border-line p-4"><Totals subtotal={c.subtotal} tax={c.tax_total} total={c.total} currency={currency} /></div>
        </Card>
      </div>
    </>
  );
}

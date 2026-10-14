import { Printer, Undo2, Ban } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  Alert, api, Badge, Button, Card, DataTable, DetailList, ErrorState, formatDate, humanise, PageHeader, quantity, Skeleton, StatusBadge, unwrap, useCan,
  useQuery, useTranslation,
} from "@/sdk";

import { ReceiptModal } from "../components/Receipt";
import { ReturnSale } from "../components/ReturnSale";
import { VoidSale } from "../components/VoidSale";
import { useBranches, useDeviceName, useMoney, useUserNames } from "../hooks";

/** One sale: what was sold and paid, who sold it, its receipt, and the ways to undo it (void while the till is open, a return after). */
export default function SalePage() {
  const { t } = useTranslation("pos");
  const { saleId = "" } = useParams();
  const canVoid = useCan("sales.void");
  const canRefund = useCan("sales.refund");
  const [receipt, setReceipt] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [returning, setReturning] = useState(false);
  const m = useMoney();
  const { nameOf } = useBranches();
  const cashier = useUserNames();
  const deviceName = useDeviceName();

  const sale = useQuery({ queryKey: ["pos-sale", saleId], queryFn: () => unwrap(api.GET("/api/v1/pos/sales/{sale_id}", { params: { path: { sale_id: saleId } } })) });
  // The receipt lists the same lines in the same order, with product names the sale itself does not carry.
  const names = useQuery({
    queryKey: ["pos-receipt", saleId], staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/pos/sales/{sale_id}/receipt", { params: { path: { sale_id: saleId }, query: { format: "json" } } })),
  });
  const till = useQuery({
    enabled: Boolean(sale.data?.till_session_id), retry: false, queryKey: ["pos-till", sale.data?.till_session_id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/tills/{till_id}", { params: { path: { till_id: sale.data?.till_session_id ?? "" } } })),
  });

  if (sale.error) return <ErrorState title={t("saleNotFound")} message={sale.error.message} onRetry={() => void sale.refetch()} />;
  const s = sale.data;
  if (!s) return <Skeleton className="h-64 w-full" />;
  const itemNames = names.data?.lines.map((l) => l.description) ?? [];
  const posted = s.status === "posted";

  return (
    <>
      <PageHeader back={{ to: "/pos/sales", label: t("allSales") }} title={s.number}
        description={<span className="flex items-center gap-2"><StatusBadge status={s.status} />{s.synced_offline && <Badge tone="info">{t("offline")}</Badge>}<span>{formatDate(s.sold_at, true)}</span></span>}
        actions={(
          <>
            <Button variant="secondary" onClick={() => setReceipt(true)}><Printer className="h-4 w-4" />{t("receipt")}</Button>
            {posted && canRefund && <Button variant="secondary" onClick={() => setReturning(true)}><Undo2 className="h-4 w-4" />{t("returnGoods")}</Button>}
            {posted && canVoid && <Button variant="danger" onClick={() => setVoiding(true)}><Ban className="h-4 w-4" />{t("voidSale")}</Button>}
          </>
        )} />
      {s.status === "voided" && <Alert tone="bad" className="mb-4">{t("voidedNote")}</Alert>}
      {s.warnings.map((w) => <Alert key={w} tone="warn" className="mb-4">{w}</Alert>)}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title={t("items")} flush>
            <DataTable rows={s.lines} rowKey={(l) => l.id} empty={{ title: t("noItems") }}
              columns={[
                { header: t("item"), cell: (l) => <span className="font-medium">{itemNames[s.lines.indexOf(l)] ?? t("itemNumber", { n: l.line_no })}</span> },
                { header: t("qty"), align: "right", cell: (l) => quantity(l.quantity) },
                { header: t("unitPrice"), hideBelow: "sm", align: "right", cell: (l) => (
                  <span>{m(l.unit_price, s.company_id)}{l.unit_price !== l.list_price && <span className="block text-xs text-warn">{t("listPrice", { price: m(l.list_price, s.company_id) })}</span>}</span>
                ) },
                { header: t("discount"), hideBelow: "md", align: "right", cell: (l) => (Number(l.discount_amount) ? m(l.discount_amount, s.company_id) : "—") },
                { header: t("tax"), hideBelow: "md", align: "right", cell: (l) => m(l.tax_amount, s.company_id) },
                { header: t("lineTotal"), align: "right", cell: (l) => <span className="font-medium">{m(l.line_total, s.company_id)}</span> },
              ]} />
          </Card>
          <Card title={t("payments")} flush>
            <DataTable rows={s.payments} rowKey={(p) => p.id} empty={{ title: t("noPayments") }}
              columns={[
                { header: t("method"), cell: (p) => t(`methods.${p.method}`, humanise(p.method)) },
                { header: t("reference"), hideBelow: "sm", cell: (p) => p.external_ref ?? "—" },
                { header: t("amount"), align: "right", cell: (p) => m(p.amount, s.company_id) },
              ]} />
          </Card>
        </div>
        <div className="space-y-4">
          <Card title={t("totals")}>
            <dl className="space-y-1.5 text-sm">
              <Line label={t("subtotal")} value={m(s.subtotal, s.company_id)} />
              {Number(s.discount_total) !== 0 && <Line label={t("discount")} value={m(s.discount_total, s.company_id)} />}
              <Line label={t("taxIncluded")} value={m(s.tax_total, s.company_id)} />
              <div className="border-t border-line pt-1.5"><Line label={t("total")} value={m(s.total, s.company_id)} strong /></div>
              {Number(s.change) > 0 && <Line label={t("change")} value={m(s.change, s.company_id)} />}
            </dl>
          </Card>
          <Card title={t("details")}>
            <DetailList items={[
              { label: t("branch"), value: nameOf(s.branch_id) },
              { label: t("cashier"), value: cashier(s.cashier_id) },
              { label: t("businessDate"), value: formatDate(s.business_date) },
              { label: t("till"), value: s.till_session_id ? (
                <Link className="text-brand hover:underline" to={`/pos/tills/${s.till_session_id}`}>{till.data ? deviceName(till.data.device_id) : t("viewTill")}</Link>
              ) : "—" },
            ]} />
          </Card>
        </div>
      </div>

      <ReceiptModal saleId={s.id} companyId={s.company_id} open={receipt} onClose={() => setReceipt(false)} />
      <VoidSale saleId={s.id} number={s.number} open={voiding} onClose={() => setVoiding(false)} />
      <ReturnSale sale={s} itemNames={itemNames} open={returning} onClose={() => setReturning(false)} />
    </>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return <div className={`flex justify-between gap-3 ${strong ? "text-base font-semibold" : ""}`}><dt className={strong ? "" : "text-muted"}>{label}</dt><dd className="tnum">{value}</dd></div>;
}

import { Lock, Printer, Receipt } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api, Button, Card, DataTable, DetailList, ErrorState, formatDate, humanise, PageHeader, Skeleton, Stat, StatusBadge, unwrap, useCan, useCompany, useQuery,
  useTranslation,
} from "@/sdk";

import { CloseTill } from "../components/CloseTill";
import { PrintArea } from "../components/PrintArea";
import { Variance } from "../components/Variance";
import { ZReportSheet } from "../components/ZReport";
import { useBranches, useDeviceName, useMoney, useUserNames } from "../hooks";

/** One till session: the figures so far (X report) or the final ones (Z report), the cash count, and a print layout for the day-end slip. */
export default function TillPage() {
  const { t } = useTranslation("pos");
  const { tillId = "" } = useParams();
  const manageOwn = useCan("till.manage");
  const reviewAny = useCan("till.review");
  const canClose = manageOwn || reviewAny;
  const [closing, setClosing] = useState(false);
  const m = useMoney();
  const { company } = useCompany();
  const { nameOf } = useBranches();
  const cashier = useUserNames();
  const deviceName = useDeviceName();

  const till = useQuery({ queryKey: ["pos-till", tillId], queryFn: () => unwrap(api.GET("/api/v1/pos/tills/{till_id}", { params: { path: { till_id: tillId } } })) });
  const report = useQuery({ queryKey: ["pos-till-report", tillId], queryFn: () => unwrap(api.GET("/api/v1/pos/tills/{till_id}/report", { params: { path: { till_id: tillId } } })) });

  const error = till.error ?? report.error;
  if (error) return <ErrorState title={t("tillNotFound")} message={error.message} onRetry={() => { void till.refetch(); void report.refetch(); }} />;
  const x = till.data, r = report.data;
  if (!x || !r) return <Skeleton className="h-64 w-full" />;
  const isOpen = x.status === "open";
  const title = `${deviceName(x.device_id)} · ${formatDate(x.business_date)}`;

  return (
    <>
      <PageHeader back={{ to: "/pos/tills", label: t("allTills") }} title={title}
        description={<span className="flex items-center gap-2"><StatusBadge status={x.status} /><span>{t("cashierName", { name: cashier(x.cashier_id) })}</span></span>}
        actions={(
          <>
            <Link to={`/pos/sales?till=${x.id}`}><Button variant="secondary"><Receipt className="h-4 w-4" />{t("viewSales")}</Button></Link>
            <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{isOpen ? t("printX") : t("printZ")}</Button>
            {isOpen && canClose && <Button onClick={() => setClosing(true)}><Lock className="h-4 w-4" />{t("closeTill")}</Button>}
          </>
        )} />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("salesTotal")} value={m(r.sales_total)} hint={t("salesCountHint", { count: r.sales_count })} />
        <Stat label={t("expectedCash")} value={m(r.expected_cash)} />
        <Stat label={t("countedCash")} value={isOpen ? "—" : m(r.counted_cash)} />
        <Stat label={t("variance")} value={<Variance value={r.variance} format={m} />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("takingsByMethod")} flush>
          <DataTable rows={Object.entries(r.takings_by_method)} rowKey={([k]) => k} empty={{ title: t("noTakings") }}
            columns={[
              { header: t("method"), cell: ([k]) => t(`methods.${k}`, humanise(k)) },
              { header: t("amount"), align: "right", cell: ([, v]) => m(v) },
            ]} />
        </Card>
        <Card title={t("cashDrawer")}>
          <dl className="space-y-1.5 text-sm">
            <Line label={t("openingFloat")} value={m(r.opening_float)} />
            <Line label={t("cashTaken")} value={m(r.takings_by_method.cash ?? "0")} />
            <Line label={t("cashRefunded")} value={m(r.cash_refunded)} />
            <div className="border-t border-line pt-1.5"><Line label={t("expectedCash")} value={m(r.expected_cash)} strong /></div>
          </dl>
        </Card>
        <Card title={t("daySummary")}>
          <DetailList items={[
            { label: t("salesCount"), value: r.sales_count },
            { label: t("salesTotal"), value: m(r.sales_total) },
            { label: t("taxIncluded"), value: m(r.tax_total) },
            { label: t("discountsGiven"), value: m(r.discount_total) },
            { label: t("voided"), value: `${r.voided_count} · ${m(r.voided_total)}` },
          ]} />
        </Card>
        <Card title={t("details")}>
          <DetailList items={[
            { label: t("till"), value: deviceName(x.device_id) },
            { label: t("branch"), value: nameOf(x.branch_id) },
            { label: t("cashier"), value: cashier(x.cashier_id) },
            { label: t("openedAt"), value: formatDate(x.opened_at, true) },
            { label: t("closedAt"), value: formatDate(x.closed_at, true) },
          ]} />
        </Card>
      </div>

      {isOpen && <CloseTill tillId={x.id} expectedCash={r.expected_cash} open={closing} onClose={() => setClosing(false)} />}
      <PrintArea>
        <ZReportSheet report={r} currency={company?.currency} closedAt={x.closed_at}
          heading={[company?.name ?? "", nameOf(x.branch_id)]}
          lines={[[t("till"), deviceName(x.device_id)], [t("cashier"), cashier(x.cashier_id)], [t("openedAt"), formatDate(x.opened_at, true)]]} />
      </PrintArea>
    </>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return <div className={`flex justify-between gap-3 ${strong ? "text-base font-semibold" : ""}`}><dt className={`min-w-0 [overflow-wrap:anywhere] ${strong ? "" : "text-muted"}`}>{label}</dt><dd className="tnum min-w-0 text-right [overflow-wrap:anywhere]">{value}</dd></div>;
}

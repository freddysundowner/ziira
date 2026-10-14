import { Printer } from "lucide-react";
import { Link } from "react-router-dom";
import { useState } from "react";

import { api, Button, Card, DataTable, Field, formatDate, Input, money, PageHeader, Stat, today, unwrap, useCurrency, useQuery, useTranslation } from "@/sdk";

import { AGE_BUCKETS, type PayableRow } from "../lib";

/** What the business owes its suppliers on posted bills, by supplier, aged by due date. */
export default function PayablesPage() {
  const { t } = useTranslation("purchasing");
  const currency = useCurrency();
  const [asOf, setAsOf] = useState(today());
  const owed = useQuery({ queryKey: ["purchasing", "payables", "all", asOf], queryFn: () => unwrap(api.GET("/api/v1/purchasing/payables", { params: { query: { as_of: asOf } } })) });
  const rows = owed.data?.suppliers as PayableRow[] | undefined;
  const late = owed.data ? AGE_BUCKETS.filter((b) => b !== "not_due").reduce((sum, b) => sum + Number(owed.data.buckets[b] ?? 0), 0) : 0;

  return (
    <>
      <PageHeader title={t("payables")} description={t("payablesHint")}
        actions={<><Field label={t("asOf")} className="flex items-center gap-2"><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
          <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("print")}</Button></>} />
      <div className="mb-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label={t("totalOwed")} value={money(owed.data?.total, currency)} loading={owed.isLoading} hint={t("asAt", { date: formatDate(owed.data?.as_of) })} />
        {AGE_BUCKETS.map((b) => <Stat key={b} label={t(`ageing.${b}`)} value={money(owed.data?.buckets[b], currency)} loading={owed.isLoading} tone={b !== "not_due" && Number(owed.data?.buckets[b]) > 0 ? "bad" : undefined} />)}
      </div>
      {late > 0 && <p className="mb-3 text-sm text-bad">{t("pastDue", { amount: money(late, currency) })}</p>}
      <Card flush>
        <DataTable rows={rows} loading={owed.isLoading} error={owed.error?.message} onRetry={() => void owed.refetch()} rowKey={(r) => r.supplier_id}
          rowHref={(r) => `/suppliers/${r.supplier_id}`} searchText={(r) => r.supplier} searchPlaceholder={t("searchSuppliers")} empty={{ title: t("owingNothing"), hint: t("owingNothingHint") }}
          columns={[
            { header: t("supplier"), sortValue: (r) => r.supplier, cell: (r) => <Link className="font-medium text-brand hover:underline" to={`/suppliers/${r.supplier_id}`}>{r.supplier}</Link> },
            ...AGE_BUCKETS.map((b) => ({ header: t(`ageing.${b}`), align: "right" as const, hideBelow: b === "not_due" ? undefined : ("md" as const), sortValue: (r: PayableRow) => Number(r[b]), cell: (r: PayableRow) => (Number(r[b]) > 0 ? money(r[b], currency) : "—") })),
            { header: t("total"), align: "right", sortValue: (r) => Number(r.total), cell: (r) => <span className="font-semibold">{money(r.total, currency)}</span> },
          ]} />
      </Card>
    </>
  );
}

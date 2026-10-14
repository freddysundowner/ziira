import { Link } from "react-router-dom";

import { api, money, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { overdueOf } from "../logic";

/** Dashboard box: what customers owe and how much of it is late. */
export default function ReceivablesWidget() {
  const { t } = useTranslation("crm");
  const { company } = useCompany();
  const q = useQuery({ queryKey: ["ageing", "widget"], queryFn: () => unwrap(api.GET("/api/v1/pos/receivables/ageing", {})), refetchInterval: 120_000 });
  if (q.error) return <p className="text-sm text-bad">{q.error.message} <button className="underline" onClick={() => void q.refetch()}>{t("retry")}</button></p>;
  if (!q.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  const overdue = overdueOf(q.data.buckets);
  return (
    <Link to="/receivables" className="block space-y-1">
      <p className="tnum text-2xl font-semibold">{money(q.data.total, company?.currency)}</p>
      <p className="text-sm text-muted">{t("owedByCustomers", { count: q.data.customers.length })}</p>
      <p className={Number(overdue) > 0 ? "text-sm font-medium text-bad" : "text-sm text-muted"}>{t("overdueAmount", { amount: money(overdue, company?.currency) })}</p>
    </Link>
  );
}

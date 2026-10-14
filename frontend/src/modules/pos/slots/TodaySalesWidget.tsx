import { Link } from "react-router-dom";

import { api, Skeleton, today, unwrap, useQuery, useTranslation } from "@/sdk";

import { useMoney } from "../hooks";
import { sumAmounts } from "../lib";

const PAGE = 200;

/** Home page box: what was sold today and how many sales that was. */
export default function TodaySalesWidget() {
  const { t } = useTranslation("pos");
  const m = useMoney();
  const sales = useQuery({
    queryKey: ["pos-today-sales"], refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/pos/sales", { params: { query: { business_date: today(), status: "posted", limit: PAGE } } })),
  });
  if (sales.error) return <p role="alert" className="text-sm text-bad">{sales.error.message}</p>;
  if (!sales.data) return <Skeleton className="h-12 w-full" />;
  const more = sales.data.length >= PAGE ? "+" : "";
  return (
    <Link to="/pos/sales" className="block">
      <p className="tnum text-2xl font-semibold">{m(String(sumAmounts(sales.data.map((s) => s.total))))}{more}</p>
      <p className="mt-1 text-xs text-muted">{t("salesToday", { count: sales.data.length })}{more}</p>
    </Link>
  );
}

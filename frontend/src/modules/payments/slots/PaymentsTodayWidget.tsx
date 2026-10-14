import { Link } from "react-router-dom";

import { api, money, today, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { PAYMENTS_PATH } from "../public";
import { summarise } from "../logic";

const WINDOW = 200;

/** Dashboard box: money received today, by method. Refreshes every minute. */
export default function PaymentsTodayWidget() {
  const { t } = useTranslation("payments");
  const { company } = useCompany();
  const day = today();
  const q = useQuery({
    queryKey: ["payments", "today", day], refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/payments/payments", { params: { query: { business_date: day, limit: WINDOW } } })),
  });
  if (q.error) return <p className="text-sm text-bad">{q.error.message} <button className="underline" onClick={() => void q.refetch()}>{t("retry")}</button></p>;
  if (!q.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  const s = summarise(q.data);
  const more = q.data.length >= WINDOW;
  return (
    <Link to={PAYMENTS_PATH} className="block space-y-2">
      <p className="tnum text-2xl font-semibold">{money(s.received, company?.currency)}{more && "+"}</p>
      <p className="text-sm text-muted">{t("receivedToday", { count: s.count })}</p>
      {s.byMethod.length === 0 ? <p className="text-sm text-muted">{t("nothingToday")}</p> : (
        <ul className="space-y-0.5 text-sm">
          {s.byMethod.map((m) => <li key={m.method} className="flex justify-between"><span className="text-muted">{t(`methods.${m.method}`, m.method)}</span><span className="tnum">{money(m.amount, company?.currency)}</span></li>)}
        </ul>
      )}
    </Link>
  );
}

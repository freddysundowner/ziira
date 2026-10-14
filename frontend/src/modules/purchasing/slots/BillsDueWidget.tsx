import { Link } from "react-router-dom";

import { api, formatDate, money, today, unwrap, useCurrency, useQuery, useTranslation } from "@/sdk";

import { SupplierName } from "../components/names";
import { addDays, amountDue, isOverdue } from "../lib";

/** Home page box: what is owed to suppliers and which bills fall due in the coming week. */
export default function BillsDueWidget() {
  const { t } = useTranslation("purchasing");
  const currency = useCurrency();
  const day = today();
  const owed = useQuery({ queryKey: ["purchasing", "payables", "all", day], queryFn: () => unwrap(api.GET("/api/v1/purchasing/payables", { params: { query: { as_of: day } } })) });
  const due = useQuery({
    queryKey: ["purchasing", "bills", "due-soon", day],
    queryFn: async () => {
      const [posted, part] = await Promise.all(["posted", "part_paid"].map((status) =>
        unwrap(api.GET("/api/v1/purchasing/bills", { params: { query: { status, due_before: addDays(day, 7), limit: 10 } } }))));
      return [...posted, ...part].sort((a, b) => a.due_date.localeCompare(b.due_date)).slice(0, 5);
    },
  });
  if (owed.error || due.error) return <p className="text-sm text-bad">{(owed.error ?? due.error)?.message}</p>;
  if (!owed.data || !due.data) return <p className="text-sm text-muted">…</p>;
  const pastDue = Object.entries(owed.data.buckets).filter(([k]) => k !== "not_due").reduce((s, [, v]) => s + Number(v), 0);

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("totalOwed")}</p><p className="tnum text-2xl font-semibold">{money(owed.data.total, currency)}</p></div>
        {pastDue > 0 && <p className="tnum text-sm font-medium text-bad">{t("pastDue", { amount: money(pastDue, currency) })}</p>}
      </div>
      {due.data.length === 0 ? <p className="text-sm text-muted">{t("nothingDueSoon")}</p> : (
        <ul className="divide-y divide-line text-sm">
          {due.data.map((b) => (
            <li key={b.id}>
              <Link to={`/bills/${b.id}`} className="flex items-center justify-between gap-3 py-2 hover:text-brand">
                <span className="min-w-0"><span className="block truncate font-medium"><SupplierName id={b.supplier_id} /></span>
                  <span className={`block text-xs ${isOverdue(b, day) ? "text-bad" : "text-muted"}`}>{isOverdue(b, day) ? t("overdueSince", { date: formatDate(b.due_date) }) : t("dueOn", { date: formatDate(b.due_date) })}</span></span>
                <span className="tnum shrink-0">{money(amountDue(b), currency)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link to="/payables" className="inline-block text-xs font-medium text-brand hover:underline">{t("seePayables")}</Link>
    </div>
  );
}

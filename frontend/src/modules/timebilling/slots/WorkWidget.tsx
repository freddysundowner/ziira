import { Link } from "react-router-dom";

import { api, money, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { useWorkCompany } from "../hooks";

/** Home page box: work not yet invoiced and timesheets waiting for approval. */
export default function WorkWidget() {
  const { t } = useTranslation("timebilling");
  const canApprove = useCan("time.approve");
  const canBill = useCan("time.bill");
  const { companyId, currency } = useWorkCompany();
  const unbilled = useQuery({
    queryKey: ["timebilling", "widget", "unbilled", companyId], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/unbilled", { params: { query: { company_id: companyId } } })),
  });
  const waiting = useQuery({
    queryKey: ["timebilling", "widget", "waiting", companyId], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/weeks", { params: { query: { company_id: companyId, status: "submitted", limit: 100 } } })),
  });
  const error = unbilled.error ?? waiting.error;
  if (error) return <p className="text-sm text-bad">{error.message}</p>;
  if (!unbilled.data || !waiting.data) return <p className="text-sm text-muted">…</p>;
  const total = unbilled.data.reduce((s, r) => s + Number(r.amount), 0);
  const count = waiting.data.length;
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("widget.unbilled")}</p><p className="tnum text-2xl font-semibold">{money(total, currency)}</p></div>
        {count > 0 && <p className="text-sm font-medium text-warn">{t("widget.waiting", { count })}</p>}
      </div>
      <p className="text-sm text-muted">{count === 0 ? t("widget.noneWaiting") : t("widget.waitingHint", { count })}</p>
      <div className="flex gap-4 text-xs font-medium text-brand-strong">
        {canBill && <Link className="hover:underline" to="/time/unbilled">{t("widget.openUnbilled")}</Link>}
        {canApprove && <Link className="hover:underline" to="/time/approvals">{t("widget.openApprovals")}</Link>}
      </div>
    </div>
  );
}

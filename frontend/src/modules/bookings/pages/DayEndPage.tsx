import { Printer } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Alert, Button, Card, DataTable, ErrorState, formatDate, Input, money, PageHeader, Stat, today, unwrap, useQuery, useTranslation, type Schemas,
} from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { useBranch } from "../hooks";

type DayEnd = Schemas["DayEndOut"];

/** What a branch took and did on a day. Print it for the drawer or the owner. */
export default function DayEndPage() {
  const { t } = useTranslation("bookings");
  const { branches, branchId, setBranchId, currency } = useBranch();
  const [day, setDay] = useState(today());
  const q = useQuery<DayEnd>({
    queryKey: ["bookings", "day-end", branchId, day], enabled: !!branchId && !!day,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/day-end", { params: { query: { branch_id: branchId, day } } })),
  });
  const d = q.data;
  const m = (v: string | number | null | undefined) => money(v, currency);
  const branchName = branches.find((b) => b.id === branchId)?.name;
  const attention = d && (d.not_billed > 0 || d.still_in > 0);

  return (
    <>
      <PageHeader title={t("dayEnd.title")} description={t("dayEnd.hint")}
        actions={<div className="flex flex-wrap items-center gap-2 print:hidden">
          <BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
          <Input type="date" aria-label={t("form.date")} className="w-44" value={day} max={today()} onChange={(e) => e.target.value && setDay(e.target.value)} />
          <Button variant="secondary" onClick={() => window.print()} disabled={!d}><Printer className="h-4 w-4" />{t("dayEnd.print")}</Button>
        </div>} />

      <p className="mb-4 hidden text-sm print:block">{branchName} · {formatDate(day)}</p>
      {q.error && <Card><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Card>}

      {!q.error && (
        <div className="space-y-6">
          {attention && d && (
            <Alert tone="warn" className="print:border print:border-line">
              <p className="font-semibold">{t("dayEnd.attention")}</p>
              <ul className="mt-1 list-disc pl-5">
                {d.not_billed > 0 && <li>{t("dayEnd.notBilledWarn", { count: d.not_billed })}</li>}
                {d.still_in > 0 && <li>{t("dayEnd.stillInWarn", { count: d.still_in })}</li>}
              </ul>
              <Link to="/front-desk" className="mt-2 inline-block font-semibold underline print:hidden">{t("dayEnd.goFrontDesk")}</Link>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label={t("dayEnd.visits")} value={d?.visits} loading={q.isLoading} />
            <Stat label={t("dayEnd.billed")} value={m(d?.billed)} loading={q.isLoading} />
            <Stat label={t("dayEnd.paid")} value={m(d?.paid)} loading={q.isLoading} tone="ok" />
            <Stat label={t("dayEnd.tips")} value={m(d?.tips_total)} loading={q.isLoading} />
            <Stat label={t("dayEnd.discounts")} value={m(d?.discounts)} loading={q.isLoading} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title={t("dayEnd.byMethod")} flush>
              <DataTable
                rows={d?.payments_by_method} loading={q.isLoading} rowKey={(r) => `${r.kind}:${r.method}`} dense
                empty={{ title: t("dayEnd.byMethodEmpty") }}
                columns={[
                  { header: t("dayEnd.method"), cell: (r) => <span className="font-medium">{t(`dayEnd.methods.${r.method}`, r.method)}{r.kind !== "payment" ? ` · ${t(`dayEnd.kinds.${r.kind}`, r.kind)}` : ""}</span> },
                  { header: t("dayEnd.count"), align: "right", hideBelow: "sm", cell: (r) => <span className="tnum">{r.n}</span> },
                  { header: t("dayEnd.amount"), align: "right", cell: (r) => <span className="tnum">{m(r.amount)}</span> },
                ]}
              />
            </Card>
            <Card title={t("dayEnd.split")}>
              <dl className="space-y-2 text-sm">
                {([["services", d?.services], ["products", d?.products], ["fees", d?.fees], ["creditUsed", d?.credit_used]] as const).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-3 border-b border-line pb-2 last:border-b-0 last:pb-0">
                    <dt className="text-muted">{t(`dayEnd.${k}`)}</dt><dd className="tnum font-semibold">{q.isLoading ? "…" : m(v)}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title={t("dayEnd.tipsByPerson")} description={t("dayEnd.tipsHint")} flush>
              <DataTable
                rows={d?.tips} loading={q.isLoading} rowKey={(r) => r.resource_id} dense empty={{ title: t("dayEnd.tipsEmpty") }}
                columns={[
                  { header: t("staffPay.person"), cell: (r) => <span className="font-medium">{r.name}</span> },
                  { header: t("dayEnd.amount"), align: "right", cell: (r) => <span className="tnum">{m(r.amount)}</span> },
                  { header: t("dayEnd.heldByUs"), align: "right", cell: (r) => <span className="tnum">{r.held_by_business ? m(r.held_by_business) : "—"}</span> },
                ]}
              />
            </Card>
            <Card title={t("dayEnd.commissionByPerson")} flush>
              <DataTable
                rows={d?.commission} loading={q.isLoading} rowKey={(r) => r.resource_id} dense empty={{ title: t("dayEnd.commissionEmpty") }}
                columns={[
                  { header: t("staffPay.person"), cell: (r) => <span className="font-medium">{r.name}</span> },
                  { header: t("dayEnd.amount"), align: "right", cell: (r) => <span className="tnum">{m(r.amount)}</span> },
                ]}
              />
            </Card>
          </div>

          <Card title={t("dayEnd.counts")}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-6">
              {([["completed", d?.completed], ["noShows", d?.no_shows], ["lateCancellations", d?.late_cancellations], ["walkIns", d?.walk_ins], ["stillIn", d?.still_in], ["notBilled", d?.not_billed]] as const).map(([k, v]) => (
                <div key={k}><dt className="eyebrow">{t(`dayEnd.${k}`)}</dt><dd className="tnum mt-0.5 text-lg font-bold">{q.isLoading ? "…" : v}</dd></div>
              ))}
            </dl>
          </Card>

          <Card title={t("dayEnd.owing")} description={t("dayEnd.owingHint")} flush>
            <DataTable
              rows={d?.owing} loading={q.isLoading} rowKey={(r) => r.number} dense empty={{ title: t("dayEnd.owingEmpty") }}
              columns={[
                { header: t("dayEnd.bill"), cell: (r) => <span className="font-medium">{r.number}</span> },
                { header: t("recalls.client"), cell: (r) => r.client_name ?? "—" },
                { header: t("dayEnd.owes"), align: "right", cell: (r) => <span className="tnum font-semibold">{m(r.owes)}</span> },
              ]}
            />
          </Card>
        </div>
      )}
    </>
  );
}

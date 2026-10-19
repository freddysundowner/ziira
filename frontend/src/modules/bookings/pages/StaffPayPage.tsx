import { useState } from "react";

import {
  api, Alert, Button, Card, ConfirmDialog, DataTable, Field, Input, money, PageHeader, Select, toast, today, unwrap, useCan, useMutation, useQuery, useTranslation, type Schemas,
} from "@/sdk";

import { useBranch, useRefreshBookings } from "../hooks";
import { CommissionRules } from "../ops/CommissionRules";
import { type Period, periodRange } from "../ops/logic";
import { Rentals } from "../ops/Rentals";

type Person = Schemas["CommissionPersonOut"];

/** What each person earned in commission (information) and the tips the business holds for them (kept apart). */
export default function StaffPayPage() {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const refresh = useRefreshBookings();
  const { branches, branchId, companyId, currency } = useBranch();
  const [period, setPeriod] = useState<Period>("thisMonth");
  const [custom, setCustom] = useState({ start: today(), end: today() });
  const [scope, setScope] = useState("");              // "" = every branch
  const [paying, setPaying] = useState<Person | null>(null);
  const range = periodRange(period, today(), custom);
  const report = useQuery<Person[]>({
    queryKey: ["bookings", "commission-report", companyId, range.start, range.end, scope], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/commission/report", { params: { query: { company_id: companyId, start: range.start, end: range.end, branch_id: scope || undefined } } })),
  });
  const payOut = useMutation({
    mutationFn: (p: Person) => unwrap(api.POST("/api/v1/bookings/tips/pay-out", { body: { company_id: companyId, resource_id: p.resource_id, branch_id: scope || null } })),
    onSuccess: (r) => { void refresh(); setPaying(null); toast(t("staffPay.tips.paid", { amount: money(r.amount, currency) }), "ok"); },
  });

  return (
    <>
      <PageHeader title={t("staffPay.title")} description={t("staffPay.hint")} />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("staffPay.period")}>
          <Select className="w-44" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
            <option value="thisMonth">{t("staffPay.thisMonth")}</option>
            <option value="lastMonth">{t("staffPay.lastMonth")}</option>
            <option value="custom">{t("staffPay.custom")}</option>
          </Select>
        </Field>
        {period === "custom" && (
          <>
            <Field label={t("staffPay.from")}><Input type="date" value={custom.start} max={custom.end} onChange={(e) => setCustom({ ...custom, start: e.target.value })} /></Field>
            <Field label={t("staffPay.to")}><Input type="date" value={custom.end} min={custom.start} onChange={(e) => setCustom({ ...custom, end: e.target.value })} /></Field>
          </>
        )}
        {branches.length > 1 && (
          <Field label={t("branch")}>
            <Select className="w-44" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">{t("staffPay.allBranches")}</option>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
        )}
      </div>

      <div className="space-y-6">
        <Card title={t("staffPay.commission.title")} flush>
          <div className="px-4 pt-4 sm:px-5"><Alert tone="info">{t("staffPay.commission.note")}</Alert></div>
          <DataTable
            rows={report.data} loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()} rowKey={(p) => p.resource_id}
            empty={{ title: t("staffPay.commission.empty"), hint: t("staffPay.commission.emptyHint") }}
            columns={[
              { header: t("staffPay.person"), sortValue: (p) => p.name, cell: (p) => <div><p className="font-medium">{p.name}</p>{p.level && <p className="text-xs text-muted">{p.level}</p>}</div> },
              { header: t("staffPay.commission.servicesSold"), hideBelow: "md", align: "right", cell: (p) => <span className="tnum">{money(p.service_sales, currency)}</span> },
              { header: t("staffPay.commission.serviceCommission"), hideBelow: "sm", align: "right", cell: (p) => <span className="tnum">{money(p.service_commission, currency)}</span> },
              { header: t("staffPay.commission.productsSold"), hideBelow: "lg", align: "right", cell: (p) => <span className="tnum">{money(p.product_sales, currency)}</span> },
              { header: t("staffPay.commission.productCommission"), hideBelow: "md", align: "right", cell: (p) => <span className="tnum">{money(p.product_commission, currency)}</span> },
              { header: t("staffPay.commission.total"), align: "right", sortValue: (p) => Number(p.commission), cell: (p) => <span className="tnum font-semibold">{money(p.commission, currency)}</span> },
            ]}
          />
        </Card>

        <Card title={t("staffPay.tips.title")} description={t("staffPay.tips.hint")} flush>
          <DataTable
            rows={report.data} loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()} rowKey={(p) => p.resource_id}
            empty={{ title: t("staffPay.tips.empty") }}
            columns={[
              { header: t("staffPay.person"), cell: (p) => <span className="font-medium">{p.name}</span> },
              { header: t("staffPay.tips.received"), align: "right", cell: (p) => <span className="tnum">{money(p.tips_received, currency)}</span> },
              { header: t("staffPay.tips.held"), align: "right", cell: (p) => <span className="tnum font-semibold">{money(p.tips_owed, currency)}</span> },
              { header: "", align: "right", cell: (p) => Number(p.tips_owed) > 0 && <Button size="sm" onClick={() => setPaying(p)}>{t("staffPay.tips.payOut")}</Button> },
            ]}
          />
        </Card>

        {canSetup && <CommissionRules companyId={companyId} branchId={branchId} currency={currency} />}
        {canSetup && <Rentals companyId={companyId} branchId={branchId} currency={currency} />}
      </div>

      <ConfirmDialog open={!!paying} onClose={() => setPaying(null)} title={t("staffPay.tips.payTitle", { name: paying?.name ?? "" })} busy={payOut.isPending}
        message={t("staffPay.tips.payMessage", { amount: money(paying?.tips_owed, currency), name: paying?.name ?? "" })}
        confirmLabel={t("staffPay.tips.payOut")} onConfirm={() => paying && payOut.mutate(paying)} />
    </>
  );
}

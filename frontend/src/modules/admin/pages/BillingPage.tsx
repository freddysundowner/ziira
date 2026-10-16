import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api, Alert, Button, ErrorState, formatDate, money, PageHeader, Skeleton, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";

import { ChangePlan } from "./billing/ChangePlan";
import { InvoicesCard } from "./billing/InvoicesCard";
import { LicencePanel } from "./billing/LicencePanel";
import { firstOwed, PLAN_KEY } from "./billing/lib";
import { PayDialog, ReturnedPayment } from "./billing/PayDialog";
import { PlanCard } from "./billing/PlanCard";
import { StateBanner } from "./billing/StateBanner";
import { UsageCard } from "./billing/UsageCard";

/** Plan & billing: the business's plan, usage, invoices and a way to ask for another plan; on a self-hosted copy, the licence. */
export default function BillingPage() {
  const { t } = useTranslation("kernel");
  const can = useCan("billing.manage");
  const { company } = useCompany();
  const location = useLocation();
  const navigate = useNavigate();
  const [paying, setPaying] = useState(false);
  const invoices = useQuery({ queryKey: ["billing-invoices"], queryFn: () => unwrap(api.GET("/api/v1/billing/invoices")), enabled: can });
  const due = firstOwed(invoices.data);
  const planQ = useQuery({ queryKey: PLAN_KEY, queryFn: () => unwrap(api.GET("/api/v1/billing/plan")), enabled: can });
  const mode = planQ.data?.mode;
  const catalog = useQuery({ queryKey: ["public-plans"], queryFn: () => unwrap(api.GET("/api/v1/public/plans")), enabled: can && mode === "saas" && planQ.data?.managed === true, staleTime: 60_000 });
  const plans = catalog.data?.plans;
  const names = useMemo(() => Object.fromEntries((plans ?? []).map((p) => [p.code, p.name])), [plans]);

  if (!can) return <ErrorState title={t("billing.noAccess")} message={t("billing.noAccessHint")} />;
  if (planQ.error) return <ErrorState title={t("billing.loadFailed")} message={planQ.error.message} onRetry={() => void planQ.refetch()} />;
  if (!planQ.data) return <Skeleton className="h-64 w-full" />;
  const plan = planQ.data;

  if (plan.mode === "selfhosted") return <LicencePanel canManage />;
  if (!plan.managed) {
    return (
      <>
        <PageHeader title={t("billing.title")} />
        <Alert tone="info">{t("billing.unmanaged")}</Alert>
      </>
    );
  }
  return (
    <>
      <PageHeader title={t("billing.title")} description={t("billing.hint")} />
      <StateBanner plan={plan} />
      {due && (
        <section className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand bg-brand-soft/30 p-4" aria-label={t("billing.dueTitle")}>
          <div>
            <p className="text-sm text-muted">{t("billing.dueTitle")}</p>
            <p className="tnum text-2xl font-semibold">{money(due.balance, due.currency.trim())}</p>
            <p className="text-sm text-muted">{t("billing.dueFor", { number: due.number ?? "", date: formatDate(due.due_date) })}</p>
          </div>
          <Button onClick={() => setPaying(true)}>{t("billing.pay.button")}</Button>
        </section>
      )}
      {paying && due && <PayDialog invoice={due} onClose={() => setPaying(false)} />}
      {location.search.includes("attempt=") && <ReturnedPayment search={location.search} onClose={() => navigate(location.pathname, { replace: true })} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <PlanCard plan={plan} planNames={names} canChange />
        <UsageCard plan={plan} />
      </div>
      {plan.payment_instructions.trim() && (
        <section className="mt-4 rounded-xl border border-line bg-surface p-4 shadow-card" aria-labelledby="billing-pay">
          <h2 id="billing-pay" className="text-sm font-semibold">{t("billing.payTitle")}</h2>
          <p className="mt-1 whitespace-pre-line text-sm text-muted">{plan.payment_instructions}</p>
        </section>
      )}
      <div className="mt-4 space-y-4">
        <InvoicesCard />
        {catalog.error ? <ErrorState title={t("billing.plansFailed")} message={catalog.error.message} onRetry={() => void catalog.refetch()} />
          : !plans ? <Skeleton className="h-48 w-full" />
          : <ChangePlan plans={plans} plan={plan} currency={plan.currency ?? company?.currency} />}
      </div>
    </>
  );
}

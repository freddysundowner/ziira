import { Outlet } from "react-router-dom";

import { PageHeader, useTranslation } from "@/sdk";

import { RouteTabs } from "../../components/RouteTabs";

/** Billing: invoices, the plan requests waiting for a decision, and the billing settings. */
export default function BillingPage() {
  const { t } = useTranslation("operator");
  return (
    <>
      <PageHeader title={t("billing.title")} description={t("billing.description")} />
      <RouteTabs label={t("billing.sections")} tabs={[
        { to: "/operator/billing/invoices", label: t("billing.tabs.invoices") },
        { to: "/operator/billing/requests", label: t("billing.tabs.requests") },
        { to: "/operator/billing/payment-attempts", label: t("billing.tabs.attempts") },
        { to: "/operator/billing/payment-methods", label: t("billing.tabs.methods") },
        { to: "/operator/billing/settings", label: t("billing.tabs.settings") },
      ]} />
      <Outlet />
    </>
  );
}

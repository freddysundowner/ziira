import { Outlet } from "react-router-dom";

import { PageHeader, useTranslation } from "@/sdk";

import { RouteTabs } from "../../components/RouteTabs";

/** Plans, add-ons and coupons: what the platform sells. */
export default function PlansPage() {
  const { t } = useTranslation("operator");
  return (
    <>
      <PageHeader title={t("plans.title")} description={t("plans.description")} />
      <RouteTabs label={t("plans.sections")} tabs={[
        { to: "/operator/plans", label: t("plans.tabs.plans"), end: true },
        { to: "/operator/plans/addons", label: t("plans.tabs.addons") },
        { to: "/operator/plans/coupons", label: t("plans.tabs.coupons") },
      ]} />
      <Outlet />
    </>
  );
}

import { PageHeader, useTranslation } from "@/sdk";

import GatewaysTab from "./billing/GatewaysTab";

/** Revenue > Payment methods: the payment providers the platform can take money through (it used to be a tab of Billing). */
export default function PaymentMethodsPage() {
  const { t } = useTranslation("operator");
  return (
    <>
      <PageHeader title={t("methods.title")} description={t("methods.description")} />
      <GatewaysTab />
    </>
  );
}

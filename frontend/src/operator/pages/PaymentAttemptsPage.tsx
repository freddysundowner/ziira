import { PageHeader, useTranslation } from "@/sdk";

import AttemptsTab from "./billing/AttemptsTab";

/** System > Payment attempts: every try a business made to pay by itself, with a way to re-check a stuck one. */
export default function PaymentAttemptsPage() {
  const { t } = useTranslation("operator");
  return (
    <>
      <PageHeader title={t("attemptsLog.title")} description={t("attemptsLog.description")} />
      <AttemptsTab />
    </>
  );
}

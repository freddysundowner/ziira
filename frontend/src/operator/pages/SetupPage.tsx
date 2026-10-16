import { PageHeader, useTranslation } from "@/sdk";

import { SetupChecklist } from "../components/SetupChecklist";

/** Overview > Setup checklist: the full "Where do I find ...?" list, always available (the dashboard shows it only until it is finished). */
export default function SetupPage() {
  const { t } = useTranslation("operator");
  return (
    <>
      <PageHeader title={t("setup.pageTitle")} description={t("setup.pageDescription")} />
      <SetupChecklist full />
    </>
  );
}

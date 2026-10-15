import { Card, useTranslation } from "@/sdk";

import { CoveragePanel } from "../components/CoveragePanel";

/** Command Center panel: what Intelligence can see, with a nudge to connect more. Receives { companyId }. */
export default function CoverageSlot({ companyId }: { companyId?: string }) {
  const { t } = useTranslation("connect");
  if (!companyId) return null;
  return <Card title={t("coverage.title")} description={t("coverage.subtitle")}><CoveragePanel companyId={companyId} compact /></Card>;
}

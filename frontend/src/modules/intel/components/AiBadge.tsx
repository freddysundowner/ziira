import { Badge, useTranslation } from "@/sdk";

/** Marks text written by the AI assistant. Always shown next to such text, so nobody mistakes it for a person's words or a calculated figure. */
export default function AiBadge({ short = false }: { short?: boolean }) {
  const { t } = useTranslation("intel");
  return <span title={t("ai.labelHint")}><Badge tone="info">{short ? t("ai.short") : t("ai.label")}</Badge></span>;
}

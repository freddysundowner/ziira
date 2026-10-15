import { Badge, useTranslation } from "@/sdk";

import { STATUS_TONE } from "../logic";

export function StatusChip({ status }: { status: string }) {
  const { t } = useTranslation("connect");
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t(`status.${status}`, { defaultValue: status })}</Badge>;
}

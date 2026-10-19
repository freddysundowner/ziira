import { Badge, useTranslation } from "@/sdk";

import { isStatus, STATUS_TONE } from "../lib";

export function AppointmentStatus({ status }: { status: string }) {
  const { t } = useTranslation("bookings");
  return <Badge tone={isStatus(status) ? STATUS_TONE[status] : "neutral"}>{t(`status.${status}`, status)}</Badge>;
}

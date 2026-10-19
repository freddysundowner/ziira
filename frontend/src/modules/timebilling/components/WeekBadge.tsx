import { Badge, type BadgeTone, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = { draft: "neutral", submitted: "warn", approved: "ok", rejected: "bad" };

/** Where a week stands, in plain words. */
export function WeekBadge({ status, pending }: { status: string; pending?: boolean }) {
  const { t } = useTranslation("timebilling");
  return <Badge tone={TONE[status] ?? "neutral"}>{t(pending && status === "submitted" ? "week.waitingInbox" : `week.${status}`)}</Badge>;
}

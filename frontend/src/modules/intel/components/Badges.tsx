import { Badge, type BadgeTone, humanise, useTranslation } from "@/sdk";

const SEVERITY_TONE: Record<string, BadgeTone> = { critical: "bad", high: "bad", medium: "warn", low: "info", info: "neutral" };
const STATUS_TONE: Record<string, BadgeTone> = { new: "brand", sent: "info", acknowledged: "warn", explained: "info", resolved: "ok", dismissed: "neutral" };

export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useTranslation("intel");
  return <Badge tone={SEVERITY_TONE[severity] ?? "neutral"}>{t(`severity.${severity}`, humanise(severity))}</Badge>;
}

export function FindingStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation("intel");
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t(`status.${status}`, humanise(status))}</Badge>;
}

/** The area of a finding or check as words; a missing area reads as general. */
export function useAreaLabel(): (area: string | null | undefined) => string {
  const { t } = useTranslation("intel");
  return (area) => t(`area.${area || "general"}`, humanise(area || "general"));
}

import { Badge, type BadgeTone, humanise, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = { critical: "bad", high: "bad", medium: "warn", low: "info", info: "neutral" };

/** A finding's severity as a coloured badge; codes this app does not know yet still read well. */
export default function Severity({ severity }: { severity: string }) {
  const { t } = useTranslation("command");
  return <Badge tone={TONE[severity] ?? "neutral"}>{t(`severity.${severity}`, humanise(severity))}</Badge>;
}

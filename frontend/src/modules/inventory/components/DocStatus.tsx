import { Badge, type BadgeTone, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = {
  draft: "neutral", pending_approval: "warn", posted: "ok", rejected: "bad", cancelled: "bad",
  dispatched: "info", received: "ok", counting: "info", review: "warn",
};

/** A stock document's status as a coloured badge with a plain-language label. */
export function DocStatus({ status }: { status: string }) {
  const { t } = useTranslation("inventory");
  return <Badge tone={TONE[status] ?? "neutral"}>{t(`docStatus.${status}`, status.replace(/_/g, " "))}</Badge>;
}

export const STATUS_FILTERS = {
  adjustments: ["draft", "pending_approval", "posted", "rejected"],
  transfers: ["draft", "dispatched", "pending_approval", "received", "cancelled"],
  counts: ["counting", "review", "pending_approval", "posted", "cancelled"],
} as const;

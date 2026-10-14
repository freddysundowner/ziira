import { Badge, type BadgeTone, humanise, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = {
  draft: "neutral", pending_approval: "warn", approved: "info", ordered: "info", sent: "info", part_received: "warn", received: "ok", closed: "neutral",
  cancelled: "bad", posted: "info", part_paid: "warn", paid: "ok", reversed: "bad", active: "ok", on_hold: "warn", inactive: "neutral",
  pending_confirmation: "warn", superseded: "neutral", matched: "ok", not_required: "neutral", exception: "bad", pending: "neutral", rejected: "bad", confirmed: "info",
};

/** A status code from the server as a coloured, translated badge (unknown codes are shown in plain words). */
export function Status({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation("purchasing");
  const code = status ?? "";
  return <Badge tone={TONE[code] ?? "neutral"}>{t(`statuses.${code}`, humanise(code))}</Badge>;
}

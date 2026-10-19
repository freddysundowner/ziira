import { Badge, useTranslation } from "@/sdk";

import { answerTone, statusTone, waitingTone } from "../lib";

/** A claim's status in plain words; a closed claim says how it closed. */
export function ClaimStatusBadge({ status, reason }: { status: string; reason?: string | null }) {
  const { t } = useTranslation("claims");
  const label = t(`status.${status}`, { defaultValue: status });
  return <Badge tone={statusTone(status)}>{status === "closed" && reason ? `${label}: ${t(`closed.${reason}`, { defaultValue: reason })}` : label}</Badge>;
}

/** Who a claim is waiting for: the payer, us or the customer. Nothing when it waits for nobody. */
export function WaitingBadge({ waiting }: { waiting: string | null | undefined }) {
  const { t } = useTranslation("claims");
  if (!waiting) return null;
  return <Badge tone={waitingTone(waiting)}>{t(`waiting.${waiting}`)}</Badge>;
}

/** The payer's answer to a line. */
export function AnswerBadge({ state }: { state: string }) {
  const { t } = useTranslation("claims");
  return <Badge tone={answerTone(state)}>{t(`answer.${state}`, { defaultValue: state })}</Badge>;
}

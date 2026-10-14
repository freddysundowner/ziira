import { Badge, Card, useTranslation } from "@/sdk";
import type { ReactNode } from "react";

export type StepState = "done" | "current" | "locked" | "skipped";

/** One numbered step of handling a request. A locked step says what to do first and shows nothing else. */
export default function StepCard({ number, title, hint, state, children }: { number: number; title: string; hint?: string; state: StepState; children: ReactNode }) {
  const { t } = useTranslation("kernel");
  const tone = state === "done" ? "ok" : state === "current" ? "brand" : "neutral";
  return (
    <Card title={`${number}. ${title}`} description={hint} actions={<Badge tone={tone}>{t(`dsr.step.${state}`)}</Badge>}
      className={state === "locked" ? "opacity-70" : undefined}>
      {state === "locked" ? <p className="text-sm text-muted">{t("dsr.step.lockedHint")}</p> : children}
    </Card>
  );
}

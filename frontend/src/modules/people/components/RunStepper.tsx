import { Check } from "lucide-react";

import { cx, useTranslation } from "@/sdk";

const STEPS = ["draft", "calculated", "pending_approval", "approved", "posted", "paid"] as const;

/** Where a run is on its way from draft to paid. A run without finance skips "posted" and shows approved as done. */
export function RunStepper({ status }: { status: string }) {
  const { t } = useTranslation("people");
  const current = STEPS.indexOf(status as (typeof STEPS)[number]);
  return (
    <ol className="mb-5 flex gap-1 overflow-x-auto rounded-xl border border-line bg-surface p-3 shadow-card" aria-label={t("run.progress")}>
      {STEPS.map((step, i) => {
        const done = current > i || status === "paid";
        const active = current === i && status !== "paid";
        return (
          <li key={step} aria-current={active ? "step" : undefined} className={cx("flex min-w-[6.5rem] flex-1 items-center gap-2 text-xs", active ? "font-semibold text-ink" : done ? "text-ink" : "text-muted")}>
            <span className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px]", done ? "border-ok bg-ok-soft text-ok" : active ? "border-brand bg-brand text-brand-ink" : "border-line")}>
              {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span>{t(`state.${step}`)}</span>
          </li>
        );
      })}
    </ol>
  );
}

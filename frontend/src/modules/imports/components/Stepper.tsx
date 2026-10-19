import { Check } from "lucide-react";

import { cx, useTranslation } from "@/sdk";

const STEPS = ["upload", "columns", "review", "import"] as const;

/** The four steps of an import, with the current one marked. */
export function Stepper({ current }: { current: number }) {
  const { t } = useTranslation("imports");
  return (
    <ol className="mb-6 flex flex-wrap gap-2" aria-label={t("steps.label")}>
      {STEPS.map((step, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={step} aria-current={active ? "step" : undefined}
            className={cx("flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm", active ? "border-brand bg-brand/10 font-medium text-ink" : "border-line text-muted")}>
            <span className={cx("flex h-5 w-5 items-center justify-center rounded-full text-xs", done ? "bg-ok text-ok-ink" : active ? "bg-brand text-white" : "bg-sunken")}>
              {done ? <Check className="h-3 w-3" /> : index + 1}
            </span>
            {t(`steps.${step}`)}
          </li>
        );
      })}
    </ol>
  );
}

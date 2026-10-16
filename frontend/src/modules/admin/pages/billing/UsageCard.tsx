import { Badge, Card, cx, quantity, useTranslation } from "@/sdk";

import { usageLevel, type MyPlan } from "./lib";

const BAR = { ok: "bg-brand", near: "bg-warn", over: "bg-bad" };
const LINES = ["users", "branches", "companies"] as const;

/** Usage against the plan's limits, and the modules the plan covers. */
export function UsageCard({ plan }: { plan: Pick<MyPlan, "usage" | "units_in_plan" | "units_over_plan"> }) {
  const { t } = useTranslation("kernel");
  return (
    <Card title={t("billing.usageTitle")} description={t("billing.usageHint")}>
      <ul className="space-y-4">
        {LINES.filter((k) => plan.usage[k]).map((k) => {
          const { used, limit } = plan.usage[k];
          const { pct, level } = usageLevel(used, limit);
          const label = t(`billing.usage.${k}`);
          return (
            <li key={k}>
              <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">{label}</span>
                <span className={cx("tnum", level === "over" && "font-semibold text-bad", level === "near" && "text-warn")}>
                  {limit === null ? t("billing.usedUnlimited", { used: quantity(used, 0) }) : t("billing.usedOf", { used: quantity(used, 0), limit: quantity(limit, 0) })}
                </span>
              </div>
              {pct !== null && (
                <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(pct, 100)} className="h-2 overflow-hidden rounded-full bg-sunken">
                  <div className={cx("h-full rounded-full", BAR[level])} style={{ width: `${Math.min(pct, 100)}%` }} />
                </div>
              )}
              {level === "over" && <p className="mt-1 text-xs text-bad">{t("billing.overLimit")}</p>}
              {level === "near" && <p className="mt-1 text-xs text-warn">{t("billing.nearLimit")}</p>}
            </li>
          );
        })}
      </ul>
      <div className="mt-5 border-t border-line pt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{t("billing.unitsTitle")}</p>
        {plan.units_in_plan === null ? <p className="text-sm text-muted">{t("billing.allUnits")}</p> : (
          <div className="flex flex-wrap gap-1.5">{plan.units_in_plan.map((u) => <Badge key={u}>{u}</Badge>)}</div>
        )}
        {plan.units_over_plan.length > 0 && (
          <div className="mt-3">
            <p className="mb-1.5 text-sm text-warn">{t("billing.unitsOver")}</p>
            <div className="flex flex-wrap gap-1.5">{plan.units_over_plan.map((u) => <Badge key={u} tone="warn">{u}</Badge>)}</div>
          </div>
        )}
      </div>
    </Card>
  );
}

import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, cx, EmptyState, useTranslation } from "@/sdk";

import type { RunException } from "../lib/types";

const ORDER = { blocker: 0, warning: 1, info: 2 } as const;
const STYLE = {
  blocker: { icon: OctagonAlert, tone: "text-bad bg-bad-soft" },
  warning: { icon: AlertTriangle, tone: "text-warn bg-warn-soft" },
  info: { icon: Info, tone: "text-info bg-info-soft" },
} as const;

/** What the reviewer should look at before submitting or approving: blockers stop the run, the rest are for review. */
export function ExceptionsCard({ exceptions, calculated }: { exceptions: RunException[]; calculated: boolean }) {
  const { t } = useTranslation("people");
  const sorted = [...exceptions].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  const blockers = exceptions.filter((e) => e.severity === "blocker").length;
  return (
    <Card title={t("run.review")} description={calculated ? t("run.reviewHint") : undefined} flush
      actions={blockers > 0 ? <span className="text-xs font-medium text-bad">{t("run.blockers", { count: blockers })}</span> : undefined}>
      {!calculated ? <EmptyState title={t("run.notCalculated")} hint={t("run.notCalculatedHint")} />
        : sorted.length === 0 ? <EmptyState title={t("run.nothingToReview")} hint={t("run.nothingToReviewHint")} />
        : (
          <ul className="divide-y divide-line">
            {sorted.map((e, i) => {
              const { icon: Icon, tone } = STYLE[e.severity];
              return (
                <li key={i} className="flex items-start gap-3 px-4 py-3 text-sm">
                  <span className={cx("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", tone)}><Icon className="h-3.5 w-3.5" /></span>
                  <div className="min-w-0 flex-1">
                    <p>{e.message}</p>
                    <p className="mt-0.5 text-xs text-muted">
                      {t(`run.severity.${e.severity}`)}
                      {e.employee_id && <> · <Link className="font-medium text-brand hover:underline" to={`/employees/${e.employee_id}`}>{e.employee_no ?? t("run.openEmployee")}</Link></>}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
    </Card>
  );
}

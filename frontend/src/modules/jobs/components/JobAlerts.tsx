import { Alert, Button, formatDate, money, useTranslation } from "@/sdk";

import type { Job } from "../types";

/**
 * What needs attention on a job, in plain words: work beyond what the customer approved, parts still to arrive, an
 * item waiting to be paid for or collected, storage owed. Each can lead to the tab where it is dealt with.
 */
export function JobAlerts({ job, currency, onTab }: { job: Job; currency: string | undefined; onTab: (tab: "estimates" | "parts" | "workshop") => void }) {
  const { t } = useTranslation("jobs");
  const approval = job.approval;
  const waitingParts = job.parts.filter((p) => !p.voided && p.source === "special_order" && p.order_status !== "arrived");
  const late = waitingParts.filter((p) => p.expected_on && new Date(p.expected_on) < new Date(new Date().toDateString()));
  const out = job.loans.filter((l) => !l.in_at);
  return (
    <div className="mb-4 space-y-2">
      {approval && approval.mode !== "off" && Number(approval.extra) > 0 && !job.locked && (
        <Alert tone={approval.mode === "block" ? "bad" : "warn"}>
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{t(job.claim ? "garage.alerts.extraClaim" : "garage.alerts.extra", { extra: money(approval.extra, currency), approved: money(approval.approved_total, currency) })}</span>
            {!job.claim && <Button size="sm" variant="secondary" onClick={() => onTab("estimates")}>{t("garage.alerts.askApproval")}</Button>}
          </span>
        </Alert>
      )}
      {waitingParts.length > 0 && (
        <Alert tone={late.length > 0 ? "warn" : "info"}>
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{late.length > 0 ? t("garage.alerts.partsLate", { count: late.length }) : t("garage.alerts.partsWaiting", { count: waitingParts.length })}</span>
            <Button size="sm" variant="secondary" onClick={() => onTab("parts")}>{t("garage.alerts.seeParts")}</Button>
          </span>
        </Alert>
      )}
      {job.release && !job.release.ok && job.release.mode !== "off" && job.status.role === "ready" && (
        <Alert tone={job.release.mode === "block" ? "bad" : "warn"}>{t(job.release.mode === "block" ? "garage.alerts.releaseBlock" : "garage.alerts.releaseWarn", { message: job.release.message ?? "" })}</Alert>
      )}
      {Number(job.storage_fee) > 0 && !job.storage_fee_waived && (
        <Alert tone="info">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{t("garage.alerts.storage", { days: job.storage_days, fee: money(job.storage_fee, currency) })}</span>
            <Button size="sm" variant="secondary" onClick={() => onTab("workshop")}>{t("garage.alerts.seeStorage")}</Button>
          </span>
        </Alert>
      )}
      {out.map((l) => (
        <Alert key={l.id} tone={l.overdue ? "warn" : "info"}>{t(l.overdue ? "garage.alerts.carOverdue" : "garage.alerts.carOut", { car: l.asset_label, date: l.due_at ? formatDate(l.due_at) : "" })}</Alert>
      ))}
    </div>
  );
}

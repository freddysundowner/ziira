import { Send, Undo2 } from "lucide-react";
import { useState } from "react";

import { Alert, api, Button, Card, ConfirmDialog, formatDate, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { useRefresh, useRequestKey } from "../hooks";
import { formatDuration } from "../lib";
import type { Week } from "../types";
import { WeekBadge } from "./WeekBadge";

/** Where this week stands, what the reviewer said, and the Submit / Recall buttons. */
export function WeekStatus({ week, companyId }: { week: Week; companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const [asking, setAsking] = useState(false);
  const { key, renew } = useRequestKey();
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/weeks/submit", { params: { header: { "Idempotency-Key": key } }, body: { company_id: companyId, week_start: week.week_start } })),
    onSuccess: () => { renew(); setAsking(false); toast(t("week.sentOk"), "ok"); void refresh(); },
  });
  const recall = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/weeks/{week_id}/recall", { params: { path: { week_id: week.week_id! } } })),
    onSuccess: () => { toast(t("week.recalledOk"), "ok"); void refresh(); },
  });
  const open = week.status === "draft" || week.status === "rejected";
  const nothing = week.minutes === 0 && week.expenses.length === 0;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <WeekBadge status={week.status} pending={week.approval_pending} />
          <p className="text-sm text-muted">
            {t("week.totals", { total: formatDuration(week.minutes), billable: formatDuration(week.billable_minutes) })}
            {week.submitted_at && week.status !== "draft" && ` · ${t("week.sentOn", { date: formatDate(week.submitted_at) })}`}
          </p>
        </div>
        {open && <Button disabled={nothing} onClick={() => setAsking(true)}><Send className="h-4 w-4" />{week.status === "rejected" ? t("week.sendAgain") : t("week.submit")}</Button>}
        {week.status === "submitted" && week.week_id && <Button variant="secondary" loading={recall.isPending} onClick={() => recall.mutate()}><Undo2 className="h-4 w-4" />{t("week.recall")}</Button>}
      </div>
      {week.status === "rejected" && (
        <Alert tone="bad" className="mt-3"><strong>{t("week.sentBack")}</strong>{week.decision_note ? ` ${week.decision_note}` : ` ${t("week.noNote")}`} {t("week.fixAndSend")}</Alert>
      )}
      {week.status === "submitted" && <Alert tone="warn" className="mt-3">{week.approval_pending ? t("week.pendingInbox") : t("week.waiting")}</Alert>}
      {week.status === "approved" && <Alert tone="ok" className="mt-3">{t("week.approvedNote")}{week.decision_note ? ` ${week.decision_note}` : ""}</Alert>}
      <ConfirmDialog open={asking} onClose={() => setAsking(false)} onConfirm={() => submit.mutate()} busy={submit.isPending}
        title={t("week.submitTitle")} confirmLabel={t("week.submit")}
        message={t("week.submitAsk", { total: formatDuration(week.minutes), expenses: week.expenses.length })} />
    </Card>
  );
}

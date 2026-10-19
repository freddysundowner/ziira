import { useState } from "react";

import { Alert, api, Button, Card, ConfirmDialog, ErrorState, Field, formatDate, Modal, Skeleton, Textarea, toast, unwrap, useMutation, useQuery, useSession, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import { formatDuration } from "../lib";
import type { Week } from "../types";
import { WeekBadge } from "./WeekBadge";
import { EntryList, ExpenseList } from "./WeekLists";

/** One person's week, read-only, with Approve / Send back (a note is needed) / Reopen. */
export function WeekReview({ weekId, currency, onClose }: { weekId: string | null; currency?: string; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const me = useSession().me?.user_id ?? null;
  const refresh = useRefresh();
  const [mode, setMode] = useState<"reject" | "reopen" | "approve" | null>(null);
  const [note, setNote] = useState("");
  const week = useQuery<Week>({
    queryKey: ["timebilling", "week-review", weekId], enabled: !!weekId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/weeks/{week_id}", { params: { path: { week_id: weekId! } } })),
  });
  const decide = useMutation({
    mutationFn: (what: "approve" | "reject" | "reopen") => {
      const path = { week_id: weekId! };
      const body = { note: note.trim() };
      if (what === "approve") return unwrap(api.POST("/api/v1/timebilling/weeks/{week_id}/approve", { params: { path }, body }));
      if (what === "reject") return unwrap(api.POST("/api/v1/timebilling/weeks/{week_id}/reject", { params: { path }, body }));
      return unwrap(api.POST("/api/v1/timebilling/weeks/{week_id}/reopen", { params: { path }, body }));
    },
    onSuccess: (_, what) => { toast(t(`approvals.done.${what}`), "ok"); setMode(null); setNote(""); void refresh(); onClose(); },
  });

  const w = week.data;
  const own = !!w && w.user_id === me;
  const expenseTotal = w ? w.expenses.length : 0;
  const closeDecision = () => { setMode(null); setNote(""); };

  return (
    <>
      <Modal open={!!weekId} onClose={onClose} size="lg" title={w ? t("approvals.weekOf", { name: w.user_name, date: formatDate(w.week_start) }) : t("approvals.week")}
        footer={w ? (
          <>
            {w.status === "approved" && !own && <Button variant="secondary" onClick={() => setMode("reopen")}>{t("approvals.reopen")}</Button>}
            {w.status === "submitted" && !own && !w.approval_pending && (
              <>
                <Button variant="secondary" onClick={() => setMode("reject")}>{t("approvals.sendBack")}</Button>
                <Button onClick={() => setMode("approve")}>{t("approvals.approve")}</Button>
              </>
            )}
            {(w.status === "draft" || w.status === "rejected" || own || w.approval_pending) && <Button variant="secondary" onClick={onClose}>{t("close")}</Button>}
          </>
        ) : undefined}>
        {week.isLoading && <Skeleton className="h-40 w-full" />}
        {week.error && <ErrorState message={week.error.message} onRetry={() => void week.refetch()} />}
        {w && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <WeekBadge status={w.status} pending={w.approval_pending} />
              <span className="text-muted">{t("week.totals", { total: formatDuration(w.minutes), billable: formatDuration(w.billable_minutes) })}</span>
              {w.submitted_at && <span className="text-muted">{t("week.sentOn", { date: formatDate(w.submitted_at) })}</span>}
            </div>
            {own && <Alert tone="info">{t("approvals.ownWeek")}</Alert>}
            {w.approval_pending && <Alert tone="warn">{t("approvals.inInbox")}</Alert>}
            {w.decision_note && <Alert tone={w.status === "rejected" ? "bad" : "info"}>{w.decision_note}</Alert>}
            <Card title={t("approvals.timeTitle")} flush><EntryList entries={w.entries} canEdit={false} showPerson={false} /></Card>
            {expenseTotal > 0 && <Card title={t("expenses.title")} flush><ExpenseList expenses={w.expenses} currency={currency} canEdit={false} /></Card>}
          </div>
        )}
      </Modal>
      <ConfirmDialog open={mode === "approve"} onClose={closeDecision} onConfirm={() => decide.mutate("approve")} busy={decide.isPending}
        title={t("approvals.approve")} confirmLabel={t("approvals.approve")}
        message={<div className="space-y-3"><p>{t("approvals.approveAsk")}</p><Field label={t("approvals.noteOptional")}><Textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field></div>} />
      <Modal open={mode === "reject" || mode === "reopen"} onClose={closeDecision} size="sm" title={t(mode === "reopen" ? "approvals.reopen" : "approvals.sendBack")}
        footer={<><Button variant="secondary" onClick={closeDecision}>{t("cancel")}</Button><Button loading={decide.isPending} disabled={!note.trim()} onClick={() => mode && decide.mutate(mode === "reopen" ? "reopen" : "reject")}>{t(mode === "reopen" ? "approvals.reopen" : "approvals.sendBack")}</Button></>}>
        <Field label={t(mode === "reopen" ? "approvals.reasonLabel" : "approvals.noteLabel")} required hint={t(mode === "reopen" ? "approvals.reopenHint" : "approvals.sendBackHint")}>
          <Textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} data-autofocus />
        </Field>
      </Modal>
    </>
  );
}

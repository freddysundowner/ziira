import { Link } from "react-router-dom";
import { useState } from "react";

import { Alert, api, Badge, Button, Card, ConfirmDialog, ErrorState, Field, Skeleton, Textarea, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { batchTone, canUndo, percentDone } from "../moveLogic";

/** Step three: the move at work (the page asks again every two seconds), then what it did, with a way back for balances and an offer to pause. */
export function MoveRunStep({ moveId, connectionId, onAgain }: { moveId: string; connectionId: string; onAgain: () => void }) {
  const { t } = useTranslation("connect");
  const qc = useQueryClient();
  const [undoing, setUndoing] = useState(false);
  const [reason, setReason] = useState("");
  const key = ["connect", "move", moveId];
  const move = useQuery({
    queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/connect/moves/{move_id}", { params: { path: { move_id: moveId } } })),
    refetchInterval: (q) => (q.state.data?.state === "done" ? false : 2000),
  });
  const conn = useQuery({ queryKey: ["connect", "connection", connectionId], queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}", { params: { path: { connection_id: connectionId } } })) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["connect"] });
  const undo = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/moves/{move_id}/undo", { params: { path: { move_id: moveId } }, body: { reason: reason.trim() } })),
    onSuccess: (m) => { qc.setQueryData(key, m); setUndoing(false); toast(t("move.run.undone"), "ok"); refresh(); },
    onError: (e) => toast(e.message, "bad"),
  });
  const pause = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/pause", { params: { path: { connection_id: connectionId } } })),
    onSuccess: () => { toast(t("move.run.paused"), "ok"); refresh(); },
    onError: (e) => toast(e.message, "bad"),
  });
  if (move.isLoading) return <Skeleton className="h-48 w-full" />;
  if (move.error || !move.data) return <ErrorState message={move.error?.message} onRetry={() => void move.refetch()} />;
  const m = move.data;
  const running = m.state === "running";
  const percent = percentDone(m.batches);
  const undoable = !running && canUndo(m.batches);
  const active = conn.data?.status === "active" || conn.data?.status === "error";

  return (
    <div className="space-y-4">
      <Card title={running ? t("move.run.running") : t("move.run.finished")} description={running ? t("move.run.runningHint") : t("move.run.finishedHint", { date: m.as_of })}>
        <div className="mb-3 h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label={t("move.run.progress")}>
          <div className="h-full bg-brand transition-all" style={{ width: `${running ? Math.max(percent, 5) : 100}%` }} />
        </div>
        <ul className="divide-y divide-line">
          {m.batches.map((b) => (
            <li key={b.kind} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-0 last:pb-0">
              <span className="min-w-0 flex-1 text-sm font-medium">{t(`move.kind.${b.kind}`)}</span>
              <Badge tone={batchTone(b)}>{t(`move.state.${b.status}`, { defaultValue: b.status })}</Badge>
              {b.status !== "waiting" && b.status !== "nothing_new" && b.status !== "unavailable" && (
                <span className="tnum text-xs text-muted">{t("move.run.counts", { imported: b.counts.imported ?? b.counts.reverted ?? 0, skipped: b.counts.skipped ?? 0, failed: b.counts.failed ?? 0 })}</span>
              )}
              {b.batch_id && <Link to={`/imports/${b.batch_id}`} className="text-xs font-medium text-brand-strong hover:underline">{t("move.run.report")}</Link>}
            </li>
          ))}
        </ul>
      </Card>
      {!running && m.needs_attention && <Alert tone="warn">{t("move.run.attention")}</Alert>}
      {!running && !m.needs_attention && <Alert tone="ok">{t("move.run.allGood")}</Alert>}
      {!running && (
        <Card title={t("move.run.next")}>
          <div className="space-y-3 text-sm">
            {active && (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 flex-1 text-muted">{t("move.run.pauseHint")}</p>
                <Button loading={pause.isPending} onClick={() => pause.mutate()}>{t("overlap.pause")}</Button>
              </div>
            )}
            {conn.data?.status === "paused" && <Alert tone="ok">{t("move.run.isPaused")}</Alert>}
            <div className="flex flex-wrap gap-2">
              <Link to="/connect"><Button variant="secondary">{t("move.run.toConnections")}</Button></Link>
              <Button variant="ghost" onClick={onAgain}>{t("move.run.again")}</Button>
              {undoable && <Button variant="danger" onClick={() => setUndoing(true)}>{t("move.run.undo")}</Button>}
            </div>
            {undoable && <p className="text-xs text-muted">{t("move.run.undoHint")}</p>}
          </div>
        </Card>
      )}
      <ConfirmDialog open={undoing} onClose={() => setUndoing(false)} onConfirm={() => (reason.trim() ? undo.mutate() : toast(t("move.run.needReason"), "bad"))} danger busy={undo.isPending}
        title={t("move.run.undoTitle")} confirmLabel={t("move.run.undo")}
        message={<div className="space-y-3"><p>{t("move.run.undoMessage")}</p><Field label={t("move.run.reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>} />
    </div>
  );
}

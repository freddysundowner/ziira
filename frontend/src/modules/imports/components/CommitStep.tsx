import { useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Badge, Button, Card, ConfirmDialog, ErrorState, Field, formatDate, money, quantity, Skeleton, Stat, StatGrid, Textarea, toast, unwrap, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import { type Batch, problemRows, progressPercent } from "../lib/wizard";
import { DownloadButton } from "./DownloadButton";

/** Step 4: the background import with its progress and, once it has finished, the reconciliation against the file. */
export function CommitStep({ batch }: { batch: Batch }) {
  const { t } = useTranslation("imports");
  const running = batch.status === "committing";
  const c = batch.counts;
  return (
    <div className="space-y-4">
      {batch.status === "reverted" && (
        <Alert tone="warn">{t("reverse.done", { date: formatDate(batch.reverted_at ?? batch.created_at), reason: batch.revert_reason ?? "" })}</Alert>
      )}
      {running ? <Progress batch={batch} /> : <Report batch={batch} />}
      <StatGrid>
        <Stat label={t("done.imported")} value={quantity(c.imported, 0)} tone={c.imported > 0 ? "ok" : undefined} />
        <Stat label={t("done.skipped")} value={quantity(c.skipped, 0)} hint={t("review.skippedHint")} />
        <Stat label={t("done.rejected")} value={quantity(c.invalid, 0)} tone={c.invalid > 0 ? "bad" : undefined} hint={t("review.problemsHint")} />
        <Stat label={t("done.failed")} value={quantity(c.failed, 0)} tone={c.failed > 0 ? "bad" : undefined} hint={t("done.failedHint")} />
      </StatGrid>
      {batch.status === "done" && batch.reversible && c.imported > 0 && <ReverseImport batch={batch} />}
      {!running && (
        <div className="flex flex-wrap justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {problemRows(c) > 0 && (
              <DownloadButton fileName="rejected-rows.csv" request={() => api.GET("/api/v1/imports/batches/{batch_id}/rejected.csv", { params: { path: { batch_id: batch.id } }, parseAs: "blob" })}>{t("review.downloadRejected")}</DownloadButton>
            )}
          </div>
          <div className="flex gap-2">
            <Link to="/imports" className="inline-flex h-9 items-center rounded-lg border border-line px-3 text-sm font-medium hover:bg-sunken">{t("done.history")}</Link>
            <Link to="/imports/new" className="inline-flex h-9 items-center rounded-lg btn-gradient px-3 text-sm font-semibold">{t("done.another")}</Link>
          </div>
        </div>
      )}
    </div>
  );
}

function Progress({ batch }: { batch: Batch }) {
  const { t } = useTranslation("imports");
  const percent = progressPercent(batch.counts);
  return (
    <Card title={t("progress.title")} description={t("progress.hint")}>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={t("progress.title")} className="h-3 overflow-hidden rounded-full bg-sunken">
        <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${percent}%` }} />
      </div>
      <p className="tnum mt-2 text-sm text-muted">{t("progress.of", { done: batch.counts.imported + batch.counts.failed, waiting: batch.counts.valid, percent })}</p>
    </Card>
  );
}

function Report({ batch }: { batch: Batch }) {
  const { t } = useTranslation("imports");
  const report = useQuery({ queryKey: ["import-report", batch.id], queryFn: () => unwrap(api.GET("/api/v1/imports/batches/{batch_id}/report", { params: { path: { batch_id: batch.id } } })) });
  if (report.isLoading) return <Skeleton className="h-40 w-full" />;
  if (report.error || !report.data) return <ErrorState message={report.error?.message} onRetry={() => void report.refetch()} />;
  const r = report.data;
  const show = (value: string, isMoney: boolean) => isMoney ? money(value) : quantity(value, 4);
  return (
    <Card title={t("report.title")} description={t("report.hint", { rows: r.rows_in_file })} flush={r.totals.length > 0}>
      {r.totals.length === 0 ? <p className="text-sm text-muted">{t("report.noTotals")}</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-sunken text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2">{t("report.figure")}</th><th className="px-4 py-2 text-right">{t("report.inFile")}</th>
                <th className="px-4 py-2 text-right">{t("report.expected")}</th><th className="px-4 py-2 text-right">{t("report.inZiira")}</th>
                <th className="px-4 py-2 text-right">{t("report.notImported")}</th><th className="px-4 py-2">{t("report.result")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {r.totals.map((x) => (
                <tr key={x.label}>
                  <td className="px-4 py-2 font-medium capitalize">{x.label}</td>
                  <td className="tnum px-4 py-2 text-right">{show(x.in_file, x.money)}</td>
                  <td className="tnum px-4 py-2 text-right">{show(x.expected, x.money)}</td>
                  <td className="tnum px-4 py-2 text-right">{show(x.in_ziira, x.money)}</td>
                  <td className="tnum px-4 py-2 text-right text-muted">{show(x.not_imported, x.money)}</td>
                  <td className="px-4 py-2">{x.matches ? <Badge tone="ok">{t("report.matches")}</Badge> : <Badge tone="bad">{t("report.differs", { amount: show(x.difference, x.money) })}</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="space-y-2 p-4">
        {r.reconciled ? <Alert tone="ok">{t("report.reconciled")}</Alert> : r.problems.map((p) => <Alert key={p} tone="warn">{p}</Alert>)}
      </div>
    </Card>
  );
}

/** Undo the whole import (opening balances): everything it created is reversed, or nothing is, with the reason shown. */
function ReverseImport({ batch }: { batch: Batch }) {
  const { t } = useTranslation("imports");
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const reverse = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/imports/batches/{batch_id}/reverse", { params: { path: { batch_id: batch.id } }, body: { reason: reason.trim() } })),
    onSuccess: () => { setOpen(false); toast(t("reverse.success"), "ok"); void qc.invalidateQueries({ queryKey: ["import", batch.id] }); void qc.invalidateQueries({ queryKey: ["import-report", batch.id] }); },
    onError: (e) => setProblem(e.message),
  });
  return (
    <Card title={t("reverse.title")} description={t("reverse.hint")}>
      <Button variant="secondary" onClick={() => { setProblem(null); setOpen(true); }}>{t("reverse.button")}</Button>
      <ConfirmDialog open={open} onClose={() => setOpen(false)} busy={reverse.isPending} danger title={t("reverse.confirmTitle")} confirmLabel={reverse.isPending ? t("reverse.working") : t("reverse.button")}
        message={
          <div className="space-y-3">
            <p>{t("reverse.confirm")}</p>
            <Field label={t("reverse.reason")} required><Textarea rows={2} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
            {problem && <Alert tone="bad">{problem}</Alert>}
          </div>
        }
        onConfirm={() => { if (reason.trim()) reverse.mutate(); else setProblem(t("reverse.needReason")); }} />
    </Card>
  );
}

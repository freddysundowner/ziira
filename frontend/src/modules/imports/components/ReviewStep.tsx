import { useState } from "react";

import {
  Alert, api, Badge, Button, Card, Checkbox, ConfirmDialog, DataTable, Pager, Select, Stat, StatGrid, StatusBadge, toast, unwrap, useMutation, usePagedList, useQueryClient,
  useTranslation, quantity,
} from "@/sdk";

import { type Batch, canImport, filterQuery, problemRows, type RowFilter } from "../lib/wizard";
import { DownloadButton } from "./DownloadButton";

const PAGE = 25;

/** Step 3: the result of the check, row by row. Nothing has been written yet. */
export function ReviewStep({ batch, onBack }: { batch: Batch; onBack: () => void }) {
  const { t } = useTranslation("imports");
  const qc = useQueryClient();
  const [filter, setFilter] = useState<RowFilter>(batch.counts.invalid > 0 ? "problems" : "all");
  const [confirming, setConfirming] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const c = batch.counts;
  const check = batch.file_check;
  const list = usePagedList(["import-rows", batch.id, filter], (limit, offset) =>
    unwrap(api.GET("/api/v1/imports/batches/{batch_id}/rows", { params: { path: { batch_id: batch.id }, query: { ...filterQuery(filter), limit, offset } } })).then((r) => r.rows), PAGE);

  const commit = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/imports/batches/{batch_id}/commit", { params: { path: { batch_id: batch.id }, query: { confirm: accepted } } })),
    onSuccess: () => { setConfirming(false); void qc.invalidateQueries({ queryKey: ["import", batch.id] }); },
    onError: (e) => { setConfirming(false); toast(e.message, "bad"); },
  });

  const filters: { id: RowFilter; label: string; count: number }[] = [
    { id: "all", label: t("review.all"), count: batch.total_rows },
    { id: "problems", label: t("review.problems"), count: problemRows(c) },
    { id: "valid", label: t("review.ready"), count: c.valid },
    { id: "skipped", label: t("review.skipped"), count: c.skipped },
  ];

  return (
    <div className="space-y-4">
      <StatGrid>
        <Stat label={t("review.inFile")} value={batch.total_rows} />
        <Stat label={t("review.ready")} value={c.valid} tone={c.valid > 0 ? "ok" : undefined} hint={t("review.readyHint")} />
        <Stat label={t("review.problems")} value={c.invalid} tone={c.invalid > 0 ? "bad" : undefined} hint={t("review.problemsHint")} />
        <Stat label={t("review.skipped")} value={c.skipped} hint={t("review.skippedHint")} />
      </StatGrid>
      {c.valid === 0 && <Alert tone="warn">{c.skipped > 0 && c.invalid === 0 ? t("review.nothingNew") : t("review.nothingReady")}</Alert>}
      {c.invalid > 0 && c.valid > 0 && !batch.whole_file && <Alert tone="info">{t("review.leftOut", { count: c.invalid })}</Alert>}
      {check.problems.map((p) => <Alert key={p} tone="bad">{p}</Alert>)}
      {check.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
      {check.confirm && !check.problems.length && (
        <Alert tone="warn">
          <div className="space-y-2">
            <p>{check.confirm}.</p>
            <Checkbox checked={accepted} onChange={(e) => setAccepted(e.target.checked)} label={t("review.acceptDifference")} />
          </div>
        </Alert>
      )}

      <Card flush>
        <DataTable
          rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => String(r.row_no)}
          toolbar={
            <Select aria-label={t("review.show")} className="max-w-xs" value={filter} onChange={(e) => setFilter(e.target.value as RowFilter)}>
              {filters.map((f) => <option key={f.id} value={f.id}>{f.label} ({quantity(f.count, 0)})</option>)}
            </Select>
          }
          empty={{ title: filter === "problems" ? t("review.noProblems") : t("review.noRows") }}
          columns={[
            { header: t("review.row"), align: "right", sortValue: (r) => r.row_no, cell: (r) => <span className="tnum text-muted">{r.row_no}</span> },
            { header: t("review.status"), cell: (r) => r.status === "invalid" ? <Badge tone="bad">{t("review.rejected")}</Badge> : r.status === "skipped" ? <Badge>{t("review.skippedOne")}</Badge> : <StatusBadge status={r.status} /> },
            { header: t("review.values"), hideBelow: "sm", cell: (r) => <span className="text-sm">{Object.values(r.values).filter(Boolean).slice(0, 3).join(" · ")}</span> },
            { header: t("review.messages"), cell: (r) => r.errors.length === 0 ? <span className="text-muted">—</span> : (
              <ul className="space-y-0.5 text-sm text-bad">{r.errors.map((m) => <li key={m} className={r.status === "skipped" ? "text-muted" : undefined}>{m}</li>)}</ul>
            ) },
          ]}
          footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        />
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={onBack}>{t("review.back")}</Button>
          {c.invalid > 0 && (
            <DownloadButton fileName="rejected-rows.csv" request={() => api.GET("/api/v1/imports/batches/{batch_id}/rejected.csv", { params: { path: { batch_id: batch.id } }, parseAs: "blob" })}>{t("review.downloadRejected")}</DownloadButton>
          )}
        </div>
        <Button disabled={!canImport(batch, accepted)} onClick={() => setConfirming(true)}>{t("review.import", { count: c.valid })}</Button>
      </div>

      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={commit.isPending} title={t("review.confirmTitle")} confirmLabel={t("review.import", { count: c.valid })}
        message={`${t("review.confirm", { count: c.valid })} ${batch.reversible ? t("review.canUndo") : t("review.noUndo")}`} onConfirm={() => commit.mutate()} />
    </div>
  );
}

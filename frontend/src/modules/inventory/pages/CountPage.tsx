import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, Checkbox, ConfirmDialog, DataTable, DetailList, formatDate, NumberInput, PageHeader, quantity, type Schemas, Select, Stat, toast, unwrap, useCan, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { DocShell } from "../components/DocShell";
import { DocStatus } from "../components/DocStatus";
import { changedCounts } from "../logic";
import { ProductName, useLocations, useReasons } from "../lookups";

type Count = Schemas["CountOut"];
type Dialog = "finish" | "submit" | "cancel" | null;

/** One stock count: enter counted quantities, finish counting, give a reason for each difference, then submit. */
export default function CountPage() {
  const { t } = useTranslation("inventory");
  const { countId = "" } = useParams();
  const qc = useQueryClient();
  const canCount = useCan("stock.count");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [why, setWhy] = useState<Record<string, string>>({});
  const [dialog, setDialog] = useState<Dialog>(null);
  const [zeroUncounted, setZeroUncounted] = useState(false);
  const locations = useLocations();
  const doc = useQuery({
    queryKey: ["inv-count", countId],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/counts/{count_id}", { params: { path: { count_id: countId } } })),
  });
  const c = doc.data;
  const reasons = useReasons("count_variance", c?.status === "review");
  const path = { params: { path: { count_id: countId } } };

  function done(next: Count, message?: string) {
    qc.setQueryData(["inv-count", countId], next);
    for (const key of ["inv-counts", "inv-balances", "inv-range-balances", "inv-movements"]) void qc.invalidateQueries({ queryKey: [key] });
    if (message) toast(message, next.status === "pending_approval" ? "info" : "ok");
    setDialog(null);
  }
  const failed = { onError: () => setDialog(null) };

  const save = useMutation({
    mutationFn: (entries: { product_id: string; batch_id: string | null; counted_qty: string }[]) => unwrap(api.POST("/api/v1/inventory/counts/{count_id}/entries", { ...path, body: { entries } })),
    onSuccess: (next) => { setTyped({}); done(next, t("countsSaved")); },
  });
  const finish = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/counts/{count_id}/finish", { ...path, body: { uncounted_as_zero: zeroUncounted } })),
    onSuccess: (next) => done(next, t("countFinished")), ...failed,
  });
  const submit = useMutation({
    mutationFn: (reasonsByLine: { line_id: string; reason_code_id: string }[]) => unwrap(api.POST("/api/v1/inventory/counts/{count_id}/submit", { ...path, body: { reasons: reasonsByLine } })),
    onSuccess: (next) => done(next, next.status === "posted" ? t("countPosted") : t("sentForApproval")), ...failed,
  });
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/counts/{count_id}/cancel", path)),
    onSuccess: (next) => done(next, t("countCancelled")), ...failed,
  });

  const lines = c?.lines ?? [];
  const counting = c?.status === "counting";
  const review = c?.status === "review";
  const edits = changedCounts(lines, typed);
  const counted = lines.filter((l) => l.counted_qty !== null).length;
  const uncounted = lines.length - counted;
  const differing = lines.filter((l) => l.variance_qty !== null && Number(l.variance_qty) !== 0);
  const reasonFor = (lineId: string, saved: string | null) => why[lineId] ?? saved ?? "";
  const missingReason = differing.some((l) => !reasonFor(l.id, l.reason_code_id));

  return (
    <DocShell loading={!c} error={doc.error?.message} onRetry={() => void doc.refetch()}>
      {c && (
        <>
          <PageHeader back={{ to: "/stock/counts", label: t("counts") }} title={c.number} description={<DocStatus status={c.status} />}
            actions={canCount && (counting || review) && (
              <>
                <Button variant="secondary" onClick={() => setDialog("cancel")}>{t("cancelCount")}</Button>
                {counting && <Button variant="secondary" disabled={edits.length === 0} loading={save.isPending}
                  onClick={() => save.mutate(edits.map(({ line, value }) => ({ product_id: line.product_id, batch_id: line.batch_id, counted_qty: value })))}>{t("saveCounts")}{edits.length > 0 && ` (${edits.length})`}</Button>}
                {counting && <Button disabled={edits.length > 0} onClick={() => setDialog("finish")}>{t("finishCounting")}</Button>}
                {review && <Button disabled={missingReason} onClick={() => setDialog("submit")}>{t("submitCount")}</Button>}
              </>
            )} />
          {counting && <Alert className="mb-4">{t("countingNote")}</Alert>}
          {review && <Alert className="mb-4">{differing.length === 0 ? t("reviewNoDifferences") : t("reviewNote")}</Alert>}
          {c.status === "pending_approval" && <Alert tone="warn" className="mb-4">{t("waitingApproval")}</Alert>}
          <div className="mb-4 grid grid-cols-3 gap-3">
            <Stat label={t("lines")} value={lines.length} />
            <Stat label={t("counted")} value={counted} hint={uncounted > 0 ? t("toGo", { count: uncounted }) : undefined} />
            <Stat label={t("differences")} value={differing.length} tone={differing.length > 0 ? "bad" : undefined} />
          </div>
          <div className="space-y-4">
            <Card>
              <DetailList items={[
                { label: t("location"), value: locations.data?.find((l) => l.id === c.location_id)?.name ?? "—" },
                { label: t("startedOn"), value: formatDate(c.snapshot_at, true) },
                { label: t("postedOn"), value: formatDate(c.posted_at, true) },
              ]} />
            </Card>
            <DataTable rows={lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
              columns={[
                { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
                { header: t("expected"), align: "right", hideBelow: "sm", cell: (l) => quantity(l.expected_qty) },
                {
                  header: t("counted"), align: "right", cell: (l) => (counting && canCount
                    ? <NumberInput className="w-28" aria-label={`${t("counted")}`} placeholder={l.counted_qty === null ? "" : quantity(l.counted_qty)} value={typed[l.id] ?? ""} onChange={(v) => setTyped({ ...typed, [l.id]: v })} />
                    : quantity(l.counted_qty)),
                },
                {
                  header: t("difference"), align: "right", cell: (l) => (l.variance_qty === null ? "—"
                    : <span className={Number(l.variance_qty) < 0 ? "font-medium text-bad" : Number(l.variance_qty) > 0 ? "font-medium text-ok" : "text-muted"}>{Number(l.variance_qty) > 0 ? "+" : ""}{quantity(l.variance_qty)}</span>),
                },
                {
                  header: t("reason"), hideBelow: "md", cell: (l) => {
                    if (l.variance_qty === null || Number(l.variance_qty) === 0) return "—";
                    if (!review || !canCount) return reasons.data?.find((r) => r.id === l.reason_code_id)?.label ?? "—";
                    return (
                      <Select aria-label={t("reason")} value={reasonFor(l.id, l.reason_code_id)} onChange={(e) => setWhy({ ...why, [l.id]: e.target.value })}>
                        <option value="">{t("chooseReason")}</option>
                        {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                      </Select>
                    );
                  },
                },
              ]} />
          </div>
          <ConfirmDialog open={dialog === "finish"} onClose={() => setDialog(null)} busy={finish.isPending} onConfirm={() => finish.mutate()}
            title={t("finishCounting")} confirmLabel={t("finishCounting")}
            message={<div className="space-y-3"><p>{t("finishAsk")}</p>{uncounted > 0 && <Checkbox label={t("uncountedAsZero", { count: uncounted })} checked={zeroUncounted} onChange={(e) => setZeroUncounted(e.target.checked)} />}</div>} />
          <ConfirmDialog open={dialog === "submit"} onClose={() => setDialog(null)} busy={submit.isPending}
            onConfirm={() => submit.mutate(differing.map((l) => ({ line_id: l.id, reason_code_id: reasonFor(l.id, l.reason_code_id) })))}
            title={t("submitCount")} confirmLabel={t("submitCount")} message={t("submitCountAsk")} />
          <ConfirmDialog open={dialog === "cancel"} onClose={() => setDialog(null)} busy={cancel.isPending} danger onConfirm={() => cancel.mutate()}
            title={t("cancelCount")} confirmLabel={t("cancelCount")} message={t("cancelCountAsk")} />
        </>
      )}
    </DocShell>
  );
}

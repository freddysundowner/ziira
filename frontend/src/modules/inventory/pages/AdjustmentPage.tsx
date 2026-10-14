import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, DataTable, DetailList, formatDate, PageHeader, quantity, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { DocShell } from "../components/DocShell";
import { DocStatus } from "../components/DocStatus";
import { ProductName, useLocations, useReasons } from "../lookups";

/** One stock adjustment: its lines, and the submit step that posts it or sends it for approval. */
export default function AdjustmentPage() {
  const { t } = useTranslation("inventory");
  const { adjustmentId = "" } = useParams();
  const qc = useQueryClient();
  const canAdjust = useCan("stock.adjust");
  const [confirming, setConfirming] = useState(false);
  const locations = useLocations();
  const reasons = useReasons("stock_adjustment");
  const doc = useQuery({
    queryKey: ["inv-adjustment", adjustmentId],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/adjustments/{adjustment_id}", { params: { path: { adjustment_id: adjustmentId } } })),
  });
  const a = doc.data;

  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/adjustments/{adjustment_id}/submit", { params: { path: { adjustment_id: adjustmentId } } })),
    onSuccess: (done) => {
      qc.setQueryData(["inv-adjustment", adjustmentId], done);
      for (const key of ["inv-adjustments", "inv-balances", "inv-range-balances", "inv-movements"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(done.status === "posted" ? t("adjustmentPosted") : t("sentForApproval"), done.status === "posted" ? "ok" : "info");
      setConfirming(false);
    },
    onError: () => setConfirming(false),
  });

  return (
    <DocShell loading={!a} error={doc.error?.message} onRetry={() => void doc.refetch()}>
      {a && (
        <>
          <PageHeader back={{ to: "/stock/adjustments", label: t("adjustments") }} title={a.number} description={<DocStatus status={a.status} />}
            actions={canAdjust && a.status === "draft" && <Button onClick={() => setConfirming(true)}>{t("submit")}</Button>} />
          {a.status === "pending_approval" && <Alert tone="warn" className="mb-4">{t("waitingApproval")}</Alert>}
          {a.status === "rejected" && <Alert tone="bad" className="mb-4">{t("rejectedNote")}</Alert>}
          {a.status === "draft" && <Alert className="mb-4">{t("draftNote")}</Alert>}
          <div className="space-y-4">
            <Card>
              <DetailList items={[
                { label: t("location"), value: locations.data?.find((l) => l.id === a.location_id)?.name ?? "—" },
                { label: t("reason"), value: reasons.data?.find((r) => r.id === a.reason_code_id)?.label ?? "—" },
                { label: t("note"), value: a.note ?? "—" },
                { label: t("postedOn"), value: formatDate(a.posted_at, true) },
              ]} />
            </Card>
            <DataTable rows={a.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
              columns={[
                { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
                { header: t("change"), align: "right", cell: (l) => <span className={Number(l.qty_change) < 0 ? "font-medium text-bad" : "font-medium text-ok"}>{Number(l.qty_change) > 0 ? "+" : ""}{quantity(l.qty_change)}</span> },
              ]} />
          </div>
          <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={submit.isPending} onConfirm={() => submit.mutate()}
            title={t("submitAdjustment")} confirmLabel={t("submit")} message={t("submitAdjustmentAsk")} />
        </>
      )}
    </DocShell>
  );
}

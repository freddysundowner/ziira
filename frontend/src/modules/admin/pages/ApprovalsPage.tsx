import { Check, X } from "lucide-react";
import { useState } from "react";

import {
  api, Button, DataTable, humanise, Modal, money, StatusBadge, Textarea, Field, toast, unwrap, useCurrency, useMutation, useQuery,
  useQueryClient, useTranslation, PageHeader, type Schemas,
} from "@/sdk";

type Request = Schemas["ziira__kernel__api__schemas__RequestOut"];

/** Requests waiting for a role the signed-in user holds. */
export default function ApprovalsPage() {
  const { t } = useTranslation("kernel");
  const [deciding, setDeciding] = useState<{ request: Request; approve: boolean } | null>(null);
  const pending = useQuery({ queryKey: ["approvals-pending"], queryFn: () => unwrap(api.GET("/api/v1/approvals/pending")) });
  return (
    <>
      <PageHeader title={t("approvals")} description={t("approvalsHint")} />
      <DataTable
        rows={pending.data} loading={pending.isLoading} error={pending.error?.message} onRetry={() => void pending.refetch()} rowKey={(r) => r.id}
        searchText={(r) => `${r.doc_type} ${r.note ?? ""}`} searchPlaceholder={t("searchApprovals")} pageSize={20}
        empty={{ title: t("noPending"), hint: t("noPendingHint") }}
        columns={[
          { header: t("docType"), sortValue: (r) => r.doc_type, cell: (r) => <span className="font-medium">{humanise(r.doc_type)}</span> },
          { header: t("amount"), align: "right", cell: (r) => <Amount request={r} /> },
          { header: t("step"), hideBelow: "md", cell: (r) => r.step },
          { header: t("status"), hideBelow: "sm", cell: (r) => <StatusBadge status={r.status} /> },
          {
            header: "", align: "right", cell: (r) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setDeciding({ request: r, approve: false })}><X className="h-4 w-4" />{t("reject")}</Button>
                <Button size="sm" onClick={() => setDeciding({ request: r, approve: true })}><Check className="h-4 w-4" />{t("approve")}</Button>
              </div>
            ),
          },
        ]}
      />
      <DecisionModal decision={deciding} onClose={() => setDeciding(null)} />
    </>
  );
}

function Amount({ request }: { request: Request }) {
  const currency = useCurrency(request.company_id ?? undefined);
  return <>{request.amount == null ? "—" : money(request.amount, currency)}</>;
}

function DecisionModal({ decision, onClose }: { decision: { request: Request; approve: boolean } | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/approvals/{request_id}/decision", {
      params: { path: { request_id: decision!.request.id } }, body: { approve: decision!.approve, note: note.trim() || null },
    })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals-pending"] });
      toast(t(decision!.approve ? "approvedDone" : "rejectedDone"), "ok");
      setNote(""); onClose();
    },
  });
  const approve = decision?.approve ?? true;
  const request = decision?.request;
  return (
    <Modal open={!!decision} onClose={onClose} title={t(approve ? "approveTitle" : "rejectTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant={approve ? "primary" : "danger"} loading={decide.isPending} onClick={() => decide.mutate()}>{t(approve ? "approve" : "reject")}</Button></>}>
      <p className="mb-3 text-sm text-muted">{request && `${humanise(request.doc_type)} · ${t("step")} ${request.step}${request.note ? ` · ${request.note}` : ""}`}</p>
      <Field label={t("comment")} hint={t("commentHint")}><Textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}

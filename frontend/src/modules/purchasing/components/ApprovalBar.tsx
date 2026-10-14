import { useState } from "react";

import { Alert, api, Button, Field, Modal, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { usePendingApproval } from "../hooks";

/**
 * Shown on a document waiting for approval. Everyone sees that it is waiting; a person who holds the approver role
 * (and did not raise it: the server refuses that) gets Approve and Reject.
 */
export function ApprovalBar({ docType, docId, waiting }: { docType: string; docId: string; waiting: boolean; }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const pending = usePendingApproval(docType, docId, waiting);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (approve: boolean) => unwrap(api.POST("/api/v1/approvals/{request_id}/decision", { params: { path: { request_id: pending.data?.id ?? "" } }, body: { approve, note: approve ? null : note.trim() || null } })),
    onSuccess: (_, approve) => {
      toast(t(approve ? "approvalApproved" : "approvalRejected"), "ok");
      setRejecting(false);
      setNote("");
      void qc.invalidateQueries({ queryKey: ["purchasing"] });
    },
  });
  if (!waiting) return null;
  return (
    <>
      <Alert tone="warn" className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <span>{pending.data ? t("approvalYours") : t("approvalWaiting")}</span>
        {pending.data && (
          <span className="flex gap-2">
            <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => setRejecting(true)}>{t("reject")}</Button>
            <Button size="sm" loading={decide.isPending} onClick={() => decide.mutate(true)}>{t("approve")}</Button>
          </span>
        )}
      </Alert>
      <Modal open={rejecting} onClose={() => setRejecting(false)} title={t("rejectTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setRejecting(false)}>{t("cancel")}</Button><Button variant="danger" loading={decide.isPending} onClick={() => decide.mutate(false)}>{t("reject")}</Button></>}>
        <Field label={t("note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} /></Field>
      </Modal>
    </>
  );
}

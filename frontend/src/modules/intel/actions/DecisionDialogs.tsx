import { useState } from "react";

import { Alert, ApiError, api, Button, Field, Modal, Textarea, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { type Proposal } from "./logic";
import { ProposalFacts } from "./ProposalParts";
import { useRefreshActions } from "./refresh";
import SchemaForm from "./SchemaForm";
import { editableFields, fieldsOf, toDraft, toValues, validate } from "./schema";

/** Approve a suggestion: look at what will happen, change the parameters that may be changed, add a note, and do it. A failed attempt stays open to try again. */
export function ApproveDialog({ proposal, onClose }: { proposal: Proposal | null; onClose: () => void }) {
  if (!proposal) return null;
  return <ApproveForm key={proposal.id} proposal={proposal} onClose={onClose} />;
}

function ApproveForm({ proposal, onClose }: { proposal: Proposal; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const refresh = useRefreshActions(proposal.finding_id);
  const allFields = fieldsOf(proposal.params_schema);
  const fields = allFields.filter((f) => f.type !== "uuid");
  const [draft, setDraft] = useState(() => toDraft(allFields, proposal.params));
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const approve = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/intel/actions/{proposal_id}/approve", {
      params: { path: { proposal_id: proposal.id } },
      body: { params: toValues(editableFields(allFields), draft), note: note.trim() || null },
    })),
    onSuccess: (done) => {
      refresh();
      if (done.status === "executed" && done.result?.ok !== false) {
        toast(done.result?.message ?? t("proposal.done"), "ok");
        onClose();
      } else {
        setFailure(done.result?.message ?? t("proposal.failedGeneric"));
      }
    },
    onError: (e) => { setFailure(e.message); toast(e.message, "bad"); },
  });

  const submit = () => {
    setChecked(true);
    if (Object.keys(validate(editableFields(allFields), draft)).length > 0) return;
    setFailure(null);
    approve.mutate();
  };
  const server = approve.error instanceof ApiError ? approve.error.fields : {};

  return (
    <Modal open onClose={onClose} title={t("proposal.approveTitle", { action: proposal.action_title })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
          <Button loading={approve.isPending} form="approve-proposal" type="submit">{failure ? t("proposal.tryAgain") : t("proposal.approveConfirm")}</Button>
        </>
      }>
      <form id="approve-proposal" className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <ProposalFacts proposal={proposal} />
        {fields.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("proposal.changeable")}</p>
            <SchemaForm fields={fields} draft={draft} onChange={(n, v) => setDraft((d) => ({ ...d, [n]: v }))} checked={checked} server={server} fixed={proposal.params} disabled={approve.isPending} />
          </div>
        )}
        <Field label={t("proposal.noteLabel")}><Textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <Alert tone="info">{t("proposal.approveNote")}</Alert>
        {failure && <Alert tone="bad">{failure}</Alert>}
      </form>
    </Modal>
  );
}

/** Turn a suggestion down; the reason is kept with the finding. */
export function RejectDialog({ proposal, onClose }: { proposal: Proposal | null; onClose: () => void }) {
  if (!proposal) return null;
  return <RejectForm key={proposal.id} proposal={proposal} onClose={onClose} />;
}

function RejectForm({ proposal, onClose }: { proposal: Proposal; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const refresh = useRefreshActions(proposal.finding_id);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const reject = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/intel/actions/{proposal_id}/reject", { params: { path: { proposal_id: proposal.id } }, body: { reason: reason.trim() } })),
    onSuccess: () => { refresh(); toast(t("proposal.turnedDown"), "ok"); onClose(); },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });
  const ready = reason.trim().length > 0;
  return (
    <Modal open onClose={onClose} title={t("proposal.rejectTitle", { action: proposal.action_title })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
          <Button variant="danger" loading={reject.isPending} disabled={!ready} form="reject-proposal" type="submit">{t("proposal.rejectConfirm")}</Button>
        </>
      }>
      <form id="reject-proposal" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) reject.mutate(); }}>
        <p className="text-sm">{proposal.description}</p>
        <Field label={t("proposal.reasonLabel")} hint={t("proposal.reasonHint")} required>
          <Textarea rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}

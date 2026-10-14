import { useState } from "react";

import { Alert, api, Button, Field, Modal, Select, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useReasons } from "../hooks";
import { ReasonDialog } from "./ReasonDialog";

/** A bill that did not match its order and receipt: shows why, and lets someone else with the right accept it (with a reason) or send it back. */
export function ExceptionPanel({ billId, notes, canDecide }: { billId: string; notes: string[]; canDecide: boolean }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const [accepting, setAccepting] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const reasons = useReasons("bill_exception", accepting);
  const reasonId = reason || reasons.data?.[0]?.id || "";
  const needsNote = !!reasons.data?.find((r) => r.id === reasonId)?.requires_note;
  const done = (key: string) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t(key), "ok"); setAccepting(false); setRejecting(false); };
  const accept = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/approve-exception", { params: { path: { bill_id: billId } }, body: { reason_code_id: reasonId, note: note.trim() || null } })),
    onSuccess: () => done("exceptionAccepted"),
  });
  const reject = useMutation({
    mutationFn: (text: string) => unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/reject-exception", { params: { path: { bill_id: billId } }, body: { note: text } })),
    onSuccess: () => done("exceptionRejected"),
  });

  return (
    <Alert tone="bad" className="mb-4 space-y-2">
      <p className="font-medium">{t("matchFailed")}</p>
      <ul className="list-disc space-y-0.5 pl-5">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
      <p className="text-xs">{canDecide ? t("exceptionSeparate") : t("exceptionWaiting")}</p>
      {canDecide && (
        <div className="flex gap-2 pt-1">
          <Button size="sm" variant="secondary" onClick={() => setRejecting(true)}>{t("sendBackToDraft")}</Button>
          <Button size="sm" onClick={() => setAccepting(true)}>{t("acceptException")}</Button>
        </div>
      )}
      <Modal open={accepting} onClose={() => setAccepting(false)} title={t("acceptException")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setAccepting(false)}>{t("cancel")}</Button><Button loading={accept.isPending} disabled={!reasonId || (needsNote && !note.trim())} onClick={() => accept.mutate()}>{t("acceptAndPost")}</Button></>}>
        <div className="space-y-4 text-ink">
          <Field label={t("reason")} required>
            <Select value={reasonId} onChange={(e) => setReason(e.target.value)}>{reasons.data?.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</Select>
          </Field>
          <Field label={t("note")} required={needsNote}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
        </div>
      </Modal>
      {rejecting && <ReasonDialog open onClose={() => setRejecting(false)} title={t("sendBackToDraft")} label={t("note")} confirmLabel={t("sendBackToDraft")} busy={reject.isPending} onSubmit={(text) => reject.mutate(text)} />}
    </Alert>
  );
}

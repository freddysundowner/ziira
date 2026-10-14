import { useState } from "react";

import {
  api, Alert, Button, ConfirmDialog, ErrorText, Field, formatDate, Select, StatusBadge, Textarea, toast, unwrap, useMutation, useQueryClient,
  useTranslation,
} from "@/sdk";

import { closingNoteOf, isFinished, type PrivacyRequest } from "./model";

/** The last step: say what was done (or why the request is refused) and close it. */
export default function CloseStep({ request, canEdit }: { request: PrivacyRequest; canEdit: boolean }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [outcome, setOutcome] = useState<"completed" | "refused">("completed");
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState(false);
  const close = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/privacy/requests/{request_id}/close", { params: { path: { request_id: request.id } }, body: { outcome, note: note.trim() } })),
    onSuccess: (r) => {
      qc.setQueryData(["privacy-request", request.id], r);
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
      toast(t("dsr.close.done"), "ok");
      setAsking(false);
    },
    onError: (e) => { setAsking(false); toast((e as Error).message, "bad"); },
  });

  if (isFinished(request)) {
    const closing = closingNoteOf(request.outcome);
    return (
      <div className="space-y-2 text-sm">
        <p><StatusBadge status={request.status} /> {request.completed_at && <span className="ml-1 text-muted">{formatDate(request.completed_at, true)}</span>}</p>
        {closing && <p className="whitespace-pre-wrap rounded-lg bg-sunken px-3 py-2">{closing}</p>}
        <p className="text-muted">{t("dsr.close.finishedHint")}</p>
      </div>
    );
  }
  if (!canEdit) return null;
  if (request.awaiting_approval) return <Alert tone="warn">{t("dsr.close.blockedByApproval")}</Alert>;

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (note.trim()) setAsking(true); }}>
      <p className="text-sm text-muted">{t(`dsr.close.intro.${request.request_type}`)}</p>
      <Field label={t("dsr.close.outcome")}>
        <Select value={outcome} onChange={(e) => setOutcome(e.target.value as "completed" | "refused")} className="max-w-xs">
          <option value="completed">{t("dsr.close.completed")}</option>
          <option value="refused">{t("dsr.close.refused")}</option>
        </Select>
      </Field>
      <Field label={t("dsr.close.note")} hint={t(outcome === "refused" ? "dsr.close.noteRefusedHint" : "dsr.close.noteHint")} required>
        <Textarea rows={3} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <ErrorText>{close.error?.message}</ErrorText>
      <Button type="submit" disabled={!note.trim()}>{t("dsr.close.button")}</Button>
      <ConfirmDialog open={asking} onClose={() => setAsking(false)} busy={close.isPending} title={t("dsr.close.confirmTitle")} confirmLabel={t("dsr.close.button")}
        message={t("dsr.close.confirmMessage")} onConfirm={() => close.mutate()} />
    </form>
  );
}

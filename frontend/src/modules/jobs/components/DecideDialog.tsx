import { useEffect, useState } from "react";

import { api, Button, Field, Input, Modal, Textarea, unwrap, useTranslation } from "@/sdk";

import { useEstimateAction } from "../hooks";
import type { Estimate } from "../types";

/** Record the customer's answer for them (they said yes or no in person or on the phone). */
export function DecideDialog({ estimate, approve, customerName, onClose }: { estimate: Estimate | null; approve: boolean; customerName: string; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => { if (estimate) { setName(customerName); setNote(""); } }, [estimate, customerName]);
  const decide = useEstimateAction((e: Estimate) => unwrap(api.POST("/api/v1/jobs/estimates/{estimate_id}/decision", { params: { path: { estimate_id: e.id } }, body: { approved: approve, customer_name: name.trim() || null, note: note.trim() || null } })),
    { done: approve ? t("estimates.approvedDone") : t("estimates.declinedDone"), onDone: onClose });
  return (
    <Modal open={estimate !== null} onClose={onClose} title={approve ? t("estimates.approveTitle") : t("estimates.declineTitle")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button variant={approve ? "primary" : "danger"} loading={decide.isPending} onClick={() => estimate && decide.mutate(estimate)}>{approve ? t("estimates.approve") : t("estimates.decline")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("estimates.decideHint")}</p>
        <Field label={t("estimates.whoSaid")}><Input maxLength={160} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("estimates.decisionNote")} hint={t("estimates.decisionNoteHint")}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

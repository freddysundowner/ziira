import { useState } from "react";

import { Button, Field, Modal, Textarea, useTranslation } from "@/sdk";

/** Asks for a written reason before something that cannot be undone (reversing a bill or a payment, rejecting an exception). */
export function ReasonDialog({ open, onClose, onSubmit, title, message, confirmLabel, busy, label }: {
  open: boolean; onClose: () => void; onSubmit: (reason: string) => void; title: string; message?: string; confirmLabel: string; busy?: boolean; label?: string;
}) {
  const { t } = useTranslation("purchasing");
  const [reason, setReason] = useState("");
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant="danger" loading={busy} disabled={!reason.trim()} onClick={() => onSubmit(reason.trim())}>{confirmLabel}</Button></>}>
      <div className="space-y-3">
        {message && <p className="text-sm text-muted">{message}</p>}
        <Field label={label ?? t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus /></Field>
      </div>
    </Modal>
  );
}

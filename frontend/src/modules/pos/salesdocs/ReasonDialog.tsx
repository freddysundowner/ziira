import { useEffect, useState } from "react";

import { Button, Field, Modal, Textarea, useTranslation } from "@/sdk";

/** Asks for the reason behind an action that undoes something (cancel an invoice, reverse a payment). */
export function ReasonDialog({ open, onClose, title, message, confirmLabel, busy, onConfirm }: {
  open: boolean; onClose: () => void; title: string; message: string; confirmLabel: string; busy?: boolean; onConfirm: (reason: string) => void;
}) {
  const { t } = useTranslation("pos");
  const [reason, setReason] = useState("");
  useEffect(() => { if (open) setReason(""); }, [open]);
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant="danger" loading={busy} disabled={!reason.trim()} onClick={() => onConfirm(reason.trim())}>{confirmLabel}</Button></>}>
      <p className="mb-3 text-sm text-muted">{message}</p>
      <Field label={t("reason")} required><Textarea value={reason} maxLength={500} rows={3} onChange={(e) => setReason(e.target.value)} /></Field>
    </Modal>
  );
}

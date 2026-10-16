import { type ReactNode, useState } from "react";

import { Button, Field, Modal, Textarea, useTranslation } from "@/sdk";

import { MIN_REASON, reasonOk } from "../lib";
import { useChange } from "../stepUp";

/**
 * Asks why, then does the change. A required reason needs a few real characters (the server holds the same rule); the
 * change asks for a fresh code when the server wants one, and the box closes only when it worked.
 */
export function ReasonDialog<R>({ title, intro, label, hint, required = true, minLength = MIN_REASON, confirmLabel, danger, run, onDone, onClose }: {
  title: string;
  intro?: ReactNode;
  label?: string;
  hint?: string;
  required?: boolean;
  minLength?: number;
  confirmLabel: string;
  danger?: boolean;
  run: (reason: string) => Promise<R>;
  onDone: (result: R) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("operator");
  const [reason, setReason] = useState("");
  const enough = required ? reasonOk(reason, minLength) : true;
  const change = useChange(() => run(reason.trim()), { onSuccess: (result) => { onDone(result); onClose(); } });
  return (
    <Modal open onClose={onClose} title={title} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="reason-form" variant={danger ? "danger" : "primary"} loading={change.isPending} disabled={!enough}>{confirmLabel}</Button>
      </>}>
      <form id="reason-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (enough && !change.isPending) change.mutate(undefined); }}>
        {intro && <div className="text-sm text-muted">{intro}</div>}
        <Field label={label ?? t("common.reason")} hint={hint} required={required}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} autoFocus />
        </Field>
      </form>
    </Modal>
  );
}

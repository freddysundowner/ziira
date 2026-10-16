import type { ReactNode } from "react";

import { Button, Modal, useTranslation } from "@/sdk";

import { useChange } from "../stepUp";

/** "Are you sure?" for a change to the platform: translated buttons, a fresh code when needed, closes when it worked. */
export function ChangeConfirm<R>({ title, message, confirmLabel, danger, run, onDone, onClose }: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  run: () => Promise<R>;
  onDone: (result: R) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("operator");
  const change = useChange(run, { onSuccess: (result) => { onDone(result); onClose(); } });
  return (
    <Modal open onClose={onClose} title={title} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button variant={danger ? "danger" : "primary"} loading={change.isPending} onClick={() => change.mutate(undefined)} data-autofocus>{confirmLabel}</Button>
      </>}>
      <div className="space-y-2 text-sm text-muted">{message}</div>
    </Modal>
  );
}

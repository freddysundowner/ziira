import { type ReactNode, useState } from "react";

import { Alert, Button, Modal, useTranslation } from "@/sdk";

import { useChange } from "../stepUp";

/**
 * A dialog with a form that makes one change: the Save button waits until the form is `ready`, asks for a fresh code when
 * the server wants one, shows the server's refusal inside the dialog, and closes when the change worked.
 */
export function ActionForm<R>({ title, submitLabel, ready = true, danger, size = "sm", run, onDone, onClose, children }: {
  title: string;
  submitLabel: string;
  ready?: boolean;
  danger?: boolean;
  size?: "sm" | "md" | "lg";
  run: () => Promise<R>;
  onDone: (result: R) => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("operator");
  const [problem, setProblem] = useState<string | null>(null);
  const change = useChange(run, { onSuccess: (result) => { onDone(result); onClose(); }, onError: (error) => setProblem(error.message) });
  const submit = () => {
    if (!ready || change.isPending) return;
    setProblem(null);
    change.mutate(undefined);
  };
  return (
    <Modal open onClose={onClose} title={title} size={size}
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="action-form" variant={danger ? "danger" : "primary"} loading={change.isPending} disabled={!ready}>{submitLabel}</Button>
      </>}>
      <form id="action-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {children}
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}

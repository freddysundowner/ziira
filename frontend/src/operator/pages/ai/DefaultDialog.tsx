import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Field, Input, Modal, Skeleton, Textarea, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";

/** Making a provider the default ends every business's consent for the old one: show how many, ask for the provider's name typed and a reason. */
export function DefaultDialog({ provider, title, onClose, onDone }: { provider: string; title: string; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation("operator");
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const preview = useQuery({ queryKey: ["operator", "ai", "default-change", provider], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai/default-change", { params: { query: { provider } } })) });
  const change = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/ai/default", { body: { provider, confirm: typed.trim(), reason: reason.trim() } })), { onSuccess: () => { onDone(); onClose(); } });
  const ready = typed.trim().toLowerCase() === provider && reason.trim().length >= 3;
  return (
    <Modal open onClose={onClose} title={t("ai.default.title", { provider: title })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="ai-default-form" variant="danger" loading={change.isPending} disabled={!ready || preview.isPending}>{t("ai.default.confirm")}</Button></>}>
      <form id="ai-default-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ready && !change.isPending) change.mutate(undefined); }}>
        {preview.isPending ? <Skeleton className="h-10 w-full" /> : preview.isError ? <Alert tone="bad">{preview.error.message}</Alert> : (
          <Alert tone="warn">{preview.data.from_provider && preview.data.from_provider !== provider
            ? t("ai.default.warning", { count: preview.data.consents_affected, from: preview.data.from_provider })
            : t("ai.default.noChange")}</Alert>
        )}
        <Field label={t("ai.default.typeLabel", { name: provider })} required><Input value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} /></Field>
        <Field label={t("common.reason")} required><Textarea rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        {change.isError && <Alert tone="bad">{change.error.message}</Alert>}
      </form>
    </Modal>
  );
}

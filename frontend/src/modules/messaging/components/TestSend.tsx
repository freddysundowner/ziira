import { useState } from "react";

import { api, Alert, Badge, Button, Field, Input, Modal, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import type { Channel } from "../providers";

/** Sends one test message and shows what became of it. */
export default function TestSend({ open, channel, companyId, onClose }: { open: boolean; channel: Channel; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("messaging");
  const qc = useQueryClient();
  const [recipient, setRecipient] = useState("");
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/test", { body: { company_id: companyId, channel, recipient: recipient.trim() } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["recent-messages"] }),
  });
  const close = () => { send.reset(); onClose(); };
  const result = send.data;
  return (
    <Modal open={open} onClose={close} title={t("testTitle", { channel: t(channel) })}
      footer={<><Button variant="secondary" onClick={close}>{t("close")}</Button><Button loading={send.isPending} disabled={!recipient.trim()} onClick={() => send.mutate()}>{t("sendTest")}</Button></>}>
      <div className="space-y-3">
        <Field label={channel === "sms" ? t("testPhone") : t("testEmail")} hint={t("testHint")}>
          <Input type={channel === "sms" ? "tel" : "email"} value={recipient} onChange={(e) => setRecipient(e.target.value)} autoFocus />
        </Field>
        {result && (
          <Alert tone={result.status === "failed" ? "bad" : "ok"}>
            <Badge tone={result.status === "failed" ? "bad" : "ok"}>{t(`status.${result.status}`, { defaultValue: result.status })}</Badge>{" "}
            {result.status === "failed" ? (result.error ?? t("failedGeneric")) : t("testQueued", { to: result.recipient })}
          </Alert>
        )}
      </div>
    </Modal>
  );
}

import { useState } from "react";

import { api, Button, Field, Input, Modal, Select, toast, unwrap, useMutation, useTranslation } from "@/sdk";

/** Record that a customer asked not to be messaged; reminders and statements then skip them. */
export function DoNotContact({ open, onClose, customerId, name }: { open: boolean; onClose: () => void; customerId: string; name: string }) {
  const { t } = useTranslation("crm");
  const [channel, setChannel] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/crm/customers/{customer_id}/do-not-contact", { params: { path: { customer_id: customerId } }, body: {
      channel: (channel || null) as "sms" | null, reason: reason.trim() || null } })),
    onSuccess: () => { toast(t("dncRecorded", { name }), "ok"); setChannel(""); setReason(""); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("doNotContact")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant="danger" loading={save.isPending} onClick={() => save.mutate()}>{t("recordOptOut")}</Button></>}>
      <p className="mb-4 text-sm text-muted">{t("dncExplain", { name })}</p>
      <div className="space-y-4">
        <Field label={t("channel")}>
          <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">{t("allChannels")}</option><option value="sms">{t("channels.sms")}</option><option value="email">{t("channels.email")}</option>
          </Select>
        </Field>
        <Field label={t("reason")}><Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} /></Field>
      </div>
    </Modal>
  );
}

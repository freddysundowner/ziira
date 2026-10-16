import { useState } from "react";

import { api, Alert, Badge, Button, Card, ConfirmDialog, DetailList, Field, Input, Modal, toast, unwrap, useMutation, useQueryClient, useTranslation, type Schemas } from "@/sdk";

/** Step 3: the number is connected. Send a test message, or disconnect it. */
export default function ConnectedCard({ companyId, state }: { companyId: string; state: Schemas["LeadIntelStateOut"] }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const [testing, setTesting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const disconnect = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/disconnect", { body: { company_id: companyId } })),
    onSuccess: () => { setRemoving(false); toast(t("disconnected"), "ok"); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
  });
  return (
    <Card title={t("connectedTitle")} actions={<Badge tone="ok">{t("status.active")}</Badge>}>
      <DetailList items={[{ label: t("number"), value: state.whatsapp?.display_phone ?? "—" }]} />
      <p className="mt-3 text-sm text-muted">{t("connectedHint")}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={() => setTesting(true)}>{t("sendTest")}</Button>
        <Button variant="ghost" onClick={() => setRemoving(true)}>{t("disconnect")}</Button>
      </div>
      <TestSend open={testing} companyId={companyId} onClose={() => setTesting(false)} />
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} busy={disconnect.isPending} danger title={t("disconnect")} confirmLabel={t("disconnect")}
        message={t("disconnectAsk")} onConfirm={() => disconnect.mutate()} />
    </Card>
  );
}

function TestSend({ open, companyId, onClose }: { open: boolean; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("leadsintel");
  const [to, setTo] = useState("");
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/test", { body: { company_id: companyId, channel: "whatsapp", recipient: to.trim() } })),
  });
  const close = () => { send.reset(); onClose(); };
  return (
    <Modal open={open} onClose={close} title={t("sendTest")}
      footer={<><Button variant="secondary" onClick={close}>{t("close")}</Button><Button loading={send.isPending} disabled={!to.trim()} onClick={() => send.mutate()}>{t("sendTest")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("testPhone")} hint={t("testHint")}><Input type="tel" value={to} onChange={(e) => setTo(e.target.value)} autoFocus /></Field>
        {send.data && <Alert tone={send.data.status === "failed" ? "bad" : "ok"}>{send.data.status === "failed" ? (send.data.error ?? t("testFailed")) : t("testQueued", { to: send.data.recipient })}</Alert>}
      </div>
    </Modal>
  );
}

import { Mail, MessageSquare } from "lucide-react";
import { useState } from "react";

import { Alert, Badge, Button, Card, ConfirmDialog, toast, unwrap, api, useCan, useMutation, useQueryClient, useTranslation, type Schemas } from "@/sdk";

import { type Channel, PROVIDERS } from "../providers";
import ChannelForm from "./ChannelForm";
import TestSend from "./TestSend";

/** One channel (SMS or email): state, set up or replace, send a test, switch off. */
export default function ChannelCard({ channel, companyId, current }: { channel: Channel; companyId: string; current?: Schemas["ChannelOut"] }) {
  const { t } = useTranslation("messaging");
  const qc = useQueryClient();
  const canEdit = useCan("settings.manage");
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/notifications/channels/{channel}", { params: { path: { channel }, query: { company_id: companyId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["notification-channels"] }); toast(t("switchedOff"), "ok"); setRemoving(false); },
  });
  const provider = PROVIDERS.find((p) => p.id === current?.provider);

  return (
    <Card
      title={<span className="inline-flex items-center gap-2">{channel === "sms" ? <MessageSquare className="h-4 w-4" /> : <Mail className="h-4 w-4" />}{t(channel)}</span>}
      actions={<Badge tone={current ? "ok" : "neutral"}>{current ? t("configured") : t("notConfigured")}</Badge>}>
      {current ? (
        <div className="space-y-3">
          <p className="text-sm">{t("sendingVia", { provider: provider?.name ?? current.provider ?? "—" })} <span className="text-muted">· {current.label}</span></p>
          <p className="text-xs text-muted">{t("secretsHidden")}</p>
        </div>
      ) : <p className="text-sm text-muted">{t(`${channel}Off`)}</p>}
      {canEdit && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => setEditing(true)} variant={current ? "secondary" : "primary"}>{current ? t("replace") : t("setUp")}</Button>
          {current && <Button variant="secondary" onClick={() => setTesting(true)}>{t("sendTest")}</Button>}
          {current && <Button variant="ghost" onClick={() => setRemoving(true)}>{t("switchOff")}</Button>}
        </div>
      )}
      {current && provider === undefined && <Alert tone="warn" className="mt-3">{t("unknownProvider")}</Alert>}
      <ChannelForm open={editing} channel={channel} companyId={companyId} replacing={!!current} onClose={() => setEditing(false)} />
      <TestSend open={testing} channel={channel} companyId={companyId} onClose={() => setTesting(false)} />
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} danger busy={remove.isPending} title={t("switchOff")} confirmLabel={t("switchOff")}
        message={t("switchOffAsk", { channel: t(channel) })} onConfirm={() => remove.mutate()} />
    </Card>
  );
}

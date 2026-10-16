import { useState } from "react";

import { api, Button, Card, channelOptions, ConfirmDialog, Field, FormGrid, Select, toast, unwrap, useChannels, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";

import BriefText from "./BriefText";

type Kind = "daily" | "weekly";

/** What my brief would say right now, with a button to send it to myself now. */
export default function PreviewCard() {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const [companyId, setCompanyId] = useState("");
  const [kind, setKind] = useState<Kind>("daily");
  const [channel, setChannel] = useState("in_app");
  const available = useChannels().data ?? [];
  const [confirm, setConfirm] = useState(false);
  const cid = companyId || company?.id;

  const preview = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/command/briefs/preview", { params: { query: { kind, company_id: cid } } })),
  });
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/command/briefs/send-now", { params: { query: { kind, channel, company_id: cid } } })),
    onSuccess: () => { setConfirm(false); void qc.invalidateQueries({ queryKey: ["command", "briefs"] }); toast(t("briefSent"), "ok"); },
    onError: () => setConfirm(false),
  });
  const onSend = () => (channel === "in_app" ? send.mutate() : setConfirm(true));

  return (
    <Card title={t("previewTitle")} description={t("previewHint")}>
      <div className="space-y-4">
        <FormGrid cols={3}>
          {companies.length > 1 && (
            <Field label={t("company")}>
              <Select value={cid ?? ""} onChange={(e) => { setCompanyId(e.target.value); preview.reset(); }}>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          )}
          <Field label={t("which")}>
            <Select value={kind} onChange={(e) => { setKind(e.target.value as Kind); preview.reset(); }}>
              <option value="daily">{t("kind.daily")}</option>
              <option value="weekly">{t("kind.weekly")}</option>
            </Select>
          </Field>
          <Field label={t("sendVia")}>
            <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {channelOptions(available, channel, ["in_app"]).map((o) => <option key={o.value} value={o.value}>{o.value === "in_app" ? t("channels.in_app") : o.label}</option>)}
            </Select>
          </Field>
        </FormGrid>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" loading={preview.isPending} disabled={!cid} onClick={() => preview.mutate()}>{t("showPreview")}</Button>
          <Button loading={send.isPending} disabled={!cid} onClick={onSend}>{t("sendNow")}</Button>
        </div>
        {preview.error && <p className="text-sm text-bad">{preview.error.message}</p>}
        {preview.data && <div className="rounded-lg border border-line bg-sunken/50 p-4"><BriefText body={preview.data.body} /></div>}
      </div>
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} onConfirm={() => send.mutate()} busy={send.isPending}
        title={t("sendNowTitle")} message={t("sendNowMessage", { channel: channelOptions(available, channel, ["in_app"]).find((o) => o.value === channel)?.label ?? channel })} confirmLabel={t("sendNow")} />
    </Card>
  );
}

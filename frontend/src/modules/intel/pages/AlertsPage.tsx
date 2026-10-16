import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Button, Card, channelOptions, EmptyState, ErrorState, Field, PageHeader, Select, SkeletonRows, toast, unwrap, useCan, useChannels, useCompany, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import SummaryStrip from "../today/SummaryStrip";

const LEVELS = ["critical", "high", "medium", "low"] as const;

/** Where you hear from Ziira: urgent alerts (the business's choice), the daily summary, and a link to each person's own channels and quiet hours. */
export default function AlertsPage() {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const { companies, company } = useCompany();
  const canSettings = useCan("settings.manage");
  const [picked, setPicked] = useState("");
  const companyId = picked || company?.id;
  const channels = useChannels(companyId).data ?? [];
  const key = ["company-settings", companyId];
  const settings = useQuery({ enabled: !!companyId && canSettings, queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } } })) });
  const [channel, setChannel] = useState("off");
  const [level, setLevel] = useState<string>("high");
  useEffect(() => { if (settings.data) { setChannel(settings.data.intel_alert_channel); setLevel(settings.data.intel_alert_min_severity); } }, [settings.data]);
  const dirty = !!settings.data && (channel !== settings.data.intel_alert_channel || level !== settings.data.intel_alert_min_severity);

  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } }, body: { intel_alert_channel: channel, intel_alert_min_severity: level as (typeof LEVELS)[number] } })),
    onSuccess: (data) => { qc.setQueryData(key, data); toast(t("alerts.saved"), "ok"); },
  });
  const options = channelOptions(channels, channel, ["off"]);

  return (
    <>
      <PageHeader title={t("alerts.title")} description={t("alerts.hint")} />
      <div className="max-w-3xl space-y-4">
        {canSettings && (
          <Card title={t("alerts.urgentTitle")} description={t("alerts.urgentHint")}>
            {companies.length > 1 && (
              <div className="mb-4 max-w-xs"><Field label={t("company")}><Select value={companyId ?? ""} onChange={(e) => setPicked(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field></div>
            )}
            {!companyId ? <EmptyState title={t("how.noCompany")} /> : settings.error ? <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} /> : !settings.data ? <SkeletonRows rows={2} cols={2} /> : (
              <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t("alerts.channel")} hint={t("alerts.channelHint")}>
                    <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
                      {options.map((o) => <option key={o.value} value={o.value}>{o.value === "off" ? t("alerts.off") : o.missing ? t("alerts.gone", { channel: o.label }) : o.label}</option>)}
                    </Select>
                  </Field>
                  <Field label={t("alerts.level")} hint={t("alerts.levelHint")}>
                    <Select value={level} onChange={(e) => setLevel(e.target.value)} disabled={channel === "off"}>
                      {LEVELS.map((l) => <option key={l} value={l}>{t(`alerts.levels.${l}`)}</option>)}
                    </Select>
                  </Field>
                </div>
                {channel === "off" && <Alert tone="info">{t("alerts.offNote")}</Alert>}
                <div className="flex justify-end"><Button type="submit" loading={save.isPending} disabled={!dirty}>{t("alerts.save")}</Button></div>
              </form>
            )}
          </Card>
        )}
        <SummaryStrip />
        <Card title={t("alerts.mineTitle")} description={t("alerts.mineHint")}>
          <Link to="/admin/account" className="text-sm font-medium text-brand-strong hover:underline">{t("alerts.mineLink")}</Link>
        </Card>
      </div>
    </>
  );
}

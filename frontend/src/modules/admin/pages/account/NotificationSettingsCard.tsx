import { type FormEvent, useState } from "react";

import {
  api, Alert, Badge, Button, Card, channelOptions, Checkbox, ConfirmDialog, ErrorState, Field, Input, Select, SkeletonRows, Switch, toast, unwrap,
  useChannels, useCompany, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { KINDS, type Kind } from "./notificationModel";

type Prefs = Schemas["PreferencesOut"];
type AvailableChannel = Schemas["AvailableChannel"];

/** My account: how I want to be messaged. A channel for each kind of message (only the channels the business has), quiet hours
 *  (read in the company's time zone), and the number I reply from (proved with a code before it counts). */
export default function NotificationSettingsCard() {
  const { t } = useTranslation("kernel");
  const prefs = useQuery({ queryKey: ["my-notification-prefs"], queryFn: () => unwrap(api.GET("/api/v1/notifications/me/preferences")) });
  const channels = useChannels();
  return (
    <Card title={t("notif.title")} description={t("notif.hint")}>
      {prefs.error ? <ErrorState message={prefs.error.message} onRetry={() => void prefs.refetch()} /> : !prefs.data || !channels.data ? <SkeletonRows rows={4} cols={2} /> : (
        <div className="space-y-6">
          <Choices prefs={prefs.data} available={channels.data} />
          {prefs.data.can_verify && <VerifiedNumber prefs={prefs.data} />}
        </div>
      )}
    </Card>
  );
}

function Choices({ prefs, available }: { prefs: Prefs; available: AvailableChannel[] }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [channels, setChannels] = useState<Record<Kind, string>>({ alerts: prefs.channels.alerts ?? "default", brief: prefs.channels.brief ?? "default", approvals: prefs.channels.approvals ?? "default" });
  const [quiet, setQuiet] = useState({ enabled: prefs.quiet_enabled, start: prefs.quiet_start, end: prefs.quiet_end, critical: prefs.quiet_critical_ok });
  const [language, setLanguage] = useState(prefs.language);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/notifications/me/preferences", { body: {
      channels, quiet_enabled: quiet.enabled, quiet_start: quiet.start, quiet_end: quiet.end,
      quiet_critical_ok: quiet.critical, language } })),
    onSuccess: (next) => { qc.setQueryData(["my-notification-prefs"], next); toast(t("notif.saved"), "ok"); },
    onError: (e) => toast(e.message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        {KINDS.map((kind) => (
          <Field key={kind} label={t(`notif.kind.${kind}`)} hint={t(`notif.kindHint.${kind}`)}>
            <Select value={channels[kind]} onChange={(e) => setChannels({ ...channels, [kind]: e.target.value })}>
              {channelOptions(available, channels[kind], ["default", "app"]).map((o) => (
                <option key={o.value} value={o.value}>{o.value === "default" || o.value === "app" ? t(`notif.choice.${o.value}`) : o.missing ? t("channelGone", { channel: o.label }) : o.label}</option>
              ))}
            </Select>
            {prefs.unavailable.includes(kind) && <p className="mt-1 text-xs text-warn">{t("channelGoneHint")}</p>}
          </Field>
        ))}
      </div>
      <Field label={t("notif.language")} hint={t("notif.languageHint")} className="max-w-xs">
        <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="en">English</option>
          <option value="sw">Kiswahili</option>
        </Select>
      </Field>
      <div className="space-y-3 rounded-lg border border-line p-3">
        <Switch label={t("notif.quiet")} checked={quiet.enabled} onChange={(v) => setQuiet({ ...quiet, enabled: v })} />
        <p className="text-xs text-muted">{t("notif.quietHint")}</p>
        {quiet.enabled && (
          <>
            <div className="grid max-w-md gap-4 sm:grid-cols-2">
              <Field label={t("notif.quietFrom")}><Input type="time" value={quiet.start} onChange={(e) => setQuiet({ ...quiet, start: e.target.value })} required /></Field>
              <Field label={t("notif.quietTo")}><Input type="time" value={quiet.end} onChange={(e) => setQuiet({ ...quiet, end: e.target.value })} required /></Field>
            </div>
            <Checkbox label={t("notif.quietCritical")} checked={quiet.critical} onChange={(e) => setQuiet({ ...quiet, critical: e.target.checked })} />
          </>
        )}
      </div>
      <Button type="submit" loading={save.isPending}>{t("notif.save")}</Button>
    </form>
  );
}

function VerifiedNumber({ prefs }: { prefs: Prefs }) {
  const { t } = useTranslation("kernel");
  const { company } = useCompany();
  const qc = useQueryClient();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [removing, setRemoving] = useState(false);
  const refresh = (next: Prefs) => qc.setQueryData(["my-notification-prefs"], next);
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/me/verified-number", { body: { company_id: company!.id, phone: phone.trim() } })),
    onSuccess: (next) => { refresh(next); setPhone(""); toast(t("notif.codeSent"), "ok"); },
    onError: (e) => toast(e.message, "bad"),
  });
  const verify = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/me/verified-number/verify", { body: { code: code.trim() } })),
    onSuccess: (next) => { refresh(next); setCode(""); toast(t("notif.verified"), "ok"); },
    onError: (e) => toast(e.message, "bad"),
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/notifications/me/verified-number")),
    onSuccess: (next) => { refresh(next); setRemoving(false); toast(t("notif.removed"), "ok"); },
  });
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold">{t("notif.numberTitle")}</h3>
      <p className="text-xs text-muted">{t("notif.numberHint")}</p>
      {prefs.number_verified ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="tnum text-sm">{prefs.verified_number}</span><Badge tone="ok">{t("notif.verifiedBadge")}</Badge>
          <Button size="sm" variant="ghost" onClick={() => setRemoving(true)}>{t("notif.remove")}</Button>
        </div>
      ) : prefs.number_pending ? (
        <form onSubmit={(e) => { e.preventDefault(); verify.mutate(); }} className="space-y-3">
          <Alert>{t("notif.codeWaiting", { phone: prefs.verified_number })}</Alert>
          <Field label={t("notif.code")}><Input inputMode="numeric" autoComplete="one-time-code" className="max-w-[10rem]" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} maxLength={10} /></Field>
          <div className="flex gap-2"><Button type="submit" loading={verify.isPending} disabled={code.length < 4}>{t("notif.verify")}</Button><Button variant="ghost" onClick={() => setRemoving(true)}>{t("notif.startOver")}</Button></div>
        </form>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); start.mutate(); }} className="flex flex-wrap items-end gap-3">
          <Field label={t("notif.phone")} hint={t("notif.phoneHint")} className="min-w-[14rem]"><Input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
          <Button type="submit" loading={start.isPending} disabled={phone.trim().length < 6 || !company}>{t("notif.sendCode")}</Button>
        </form>
      )}
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} busy={remove.isPending} danger title={t("notif.remove")} confirmLabel={t("notif.remove")}
        message={t("notif.removeAsk")} onConfirm={() => remove.mutate()} />
    </div>
  );
}

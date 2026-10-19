import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";

import { Alert, Badge, Button, Card, ErrorState, Field, Input, PageHeader, Select, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { useOperatorCan } from "../me";
import { useChange } from "../stepUp";
import { useRefreshOperator } from "./billing/invoiceDialogs";

const KEY = ["operator", "behaviour"];
const MODES = ["open", "invite", "closed"] as const;

/** Platform > Settings: registration mode, defaults for new businesses, and the public addresses and links. */
export default function PlatformSettingsPage() {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.settings");
  const page = useQuery({ queryKey: KEY, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/platform/behaviour")) });
  if (page.isPending) return <Skeleton className="h-64 w-full" />;
  if (page.isError) return <ErrorState title={t("psettings.loadFailed")} message={page.error.message} onRetry={() => void page.refetch()} />;
  const d = page.data;
  const row = (key: string, label: string, hint?: string, input?: "text" | "number") => (
    <SettingRow key={`${key}:${JSON.stringify(d.values[key]?.value)}`} settingKey={key} label={label} hint={hint} stored={d.values[key]} editable={editable} type={input} />
  );
  return (
    <div className="space-y-5">
      <PageHeader title={t("psettings.title")} description={t("psettings.intro")} />
      {!editable && <Alert tone="info">{t("psettings.readOnly")}</Alert>}
      <Card title={t("psettings.registration.title")}>
        <div className="space-y-4">
          <ModeRow stored={String(d.values["registration.mode"]?.value || d.values["registration.mode"]?.effective || "closed")} editable={editable} />
          {!d.email_working && (
            <Alert tone="warn">{t("psettings.registration.needsEmail")} {d.email_reason} <Link className="font-medium underline" to="/operator/email">{t("nav.email")}</Link></Alert>
          )}
          <SettingRow key={`edition:${String(d.values["registration.default_edition"]?.value)}`} settingKey="registration.default_edition" label={t("psettings.registration.edition")}
            hint={t("psettings.registration.editionHint")} stored={d.values["registration.default_edition"]} editable={editable} choices={d.editions} />
          {row("registration.trial_days", t("psettings.registration.trial"), t("psettings.registration.trialHint"), "number")}
          {row("registration.default_country", t("psettings.registration.country"), t("psettings.registration.countryHint"))}
        </div>
      </Card>
      <Card title={t("psettings.public.title")} description={t("psettings.public.hint")}>
        <div className="space-y-4">
          {row("public.web_url", t("psettings.public.webUrl"), t("psettings.public.webUrlHint"))}
          {row("public.api_url", t("psettings.public.apiUrl"), t("psettings.public.apiUrlHint"))}
          {row("public.terms_url", t("psettings.public.terms"))}
          {row("public.privacy_url", t("psettings.public.privacy"))}
          {row("public.help_url", t("psettings.public.help"))}
          {row("public.site_url", t("psettings.public.site"))}
          {row("public.support_email", t("psettings.public.support"))}
        </div>
      </Card>
    </div>
  );
}

function useSave(key: string, label: string, onProblem: (m: string | null) => void) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  return useChange((value: string) => opUnwrap(opApi.PUT("/api/v1/operator/platform/behaviour/{key}", { params: { path: { key } }, body: { value } })), {
    onSuccess: () => { onProblem(null); toast(t("psettings.saved", { name: label }), "ok"); refresh(); },
    onError: (e) => onProblem(e.message),
  });
}

function ModeRow({ stored, editable }: { stored: string; editable: boolean }) {
  const { t } = useTranslation("operator");
  const [mode, setMode] = useState(stored);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useSave("registration.mode", t("psettings.registration.mode"), setProblem);
  return (
    <div className="space-y-2">
      <Field label={t("psettings.registration.mode")}>
        <Select value={mode} disabled={!editable} onChange={(e) => { setMode(e.target.value); setProblem(null); }}>
          {MODES.map((m) => <option key={m} value={m}>{t(`psettings.registration.${m}`)}</option>)}
        </Select>
      </Field>
      {problem && <Alert tone="bad">{problem}</Alert>}
      {editable && <div className="flex justify-end"><Button size="sm" loading={save.isPending} disabled={mode === stored} onClick={() => save.mutate(mode)}>{t("psettings.save")}</Button></div>}
    </div>
  );
}

function SettingRow({ settingKey, label, hint, stored, editable, choices, type }: {
  settingKey: string; label: string; hint?: string; stored: { value: unknown; effective: string; source: string } | undefined; editable: boolean; choices?: string[]; type?: "text" | "number";
}) {
  const { t } = useTranslation("operator");
  const initial = stored?.value === undefined || stored.value === null ? "" : String(stored.value);
  const [value, setValue] = useState(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useSave(settingKey, label, setProblem);
  const fromEnv = initial === "" && stored?.source === "environment";
  return (
    <div className="space-y-2">
      <Field label={label} hint={fromEnv ? `${t("psettings.fromEnv")}: ${stored?.effective}` : hint}>
        {choices ? (
          <Select value={value} disabled={!editable} onChange={(e) => { setValue(e.target.value); setProblem(null); }}>
            <option value="">{t("psettings.unset")}</option>
            {choices.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        ) : (
          <Input value={value} disabled={!editable} maxLength={300} inputMode={type === "number" ? "numeric" : undefined} onChange={(e) => { setValue(e.target.value); setProblem(null); }} />
        )}
      </Field>
      {fromEnv && <Badge tone="neutral">{t("psettings.fromEnv")}</Badge>}
      {problem && <Alert tone="bad">{problem}</Alert>}
      {editable && value !== initial && <div className="flex justify-end"><Button size="sm" loading={save.isPending} onClick={() => save.mutate(value.trim())}>{t("psettings.save")}</Button></div>}
    </div>
  );
}

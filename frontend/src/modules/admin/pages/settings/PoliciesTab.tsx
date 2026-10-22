import {
  api, channelOptions, formatBytes, Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, NumberInput, Select, SkeletonRows, Switch, toast, unwrap, useCurrency,
  useChannels, useMutation, useSession, useQuery, useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";
import { useEffect, useState } from "react";

import { type FormValues, GROUPS, type SettingField, toForm, toPatch, WEEKDAYS } from "./model";

const CHANNEL_FIELDS: string[] = ["reminder_channel", "intel_alert_channel"];
/** Groups that are rarely changed: kept behind "More options". */
const RARE = ["alerts", "privacy", "files"];

/** How much space the company's photos and files use now, and the plan's limit when it has one. */
function FilesUsage({ companyId }: { companyId: string }) {
  const { t } = useTranslation("kernel");
  const usage = useQuery({
    queryKey: ["files-usage", companyId], retry: false,
    queryFn: () => unwrap(api.GET("/api/v1/files/usage", { params: { query: { company_id: companyId } } })),
  });
  if (!usage.data) return null;
  const { files, bytes, plan_limit_bytes: plan } = usage.data;
  return (
    <p className="mt-3 border-t border-line pt-3 text-xs text-muted">
      {t("filesUsage", { files, size: formatBytes(bytes) })}{plan != null ? ` ${t("filesUsagePlan", { size: formatBytes(plan) })}` : ""}
    </p>
  );
}

export default function PoliciesTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const key = ["company-settings", companyId];
  const settings = useQuery({
    enabled: !!companyId, queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } } })),
  });
  const channels = useChannels(companyId);
  const { enabledUnits } = useSession();
  const [form, setForm] = useState<FormValues | null>(null);
  useEffect(() => { if (settings.data) setForm(toForm(settings.data)); }, [settings.data]);

  const original = settings.data ? toForm(settings.data) : null;
  const patch = original && form ? toPatch(original, form) : {};
  const dirty = Object.keys(patch).length > 0;
  useUnsavedWarning(dirty);

  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } }, body: patch })),
    onSuccess: (data) => { qc.setQueryData(key, data); toast(t("settingsSaved"), "ok"); },
  });

  if (!companyId) return <EmptyState title={t("noCompany")} />;
  if (settings.error) return <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />;
  if (!form) return <SkeletonRows rows={6} cols={2} />;

  const set = (k: string, v: string) => setForm({ ...form, [k]: v });
  const weekdays = form.weekend_days ? form.weekend_days.split(",") : [];

  const control = (f: SettingField) => {
    const value = form[f.key];
    const label = t(`set.${f.key}`);
    if (f.kind === "switch") return <Switch label={label} checked={value === "true"} onChange={(v) => set(f.key, String(v))} />;
    if (f.kind === "choice" && CHANNEL_FIELDS.includes(f.key)) {
      // The channels the business has now (a plugin that is off offers none); a stored value that is gone stays visible.
      const options = channelOptions(channels.data ?? [], value, ["off"]);
      const gone = options.find((o) => o.missing);
      return (
        <div className="space-y-1">
          <Select value={value} onChange={(e) => set(f.key, e.target.value)}>
            {options.map((o) => <option key={o.value} value={o.value}>{o.value === "off" ? t(`choice.${f.key}.off`) : o.missing ? t("channelGone", { channel: o.label }) : o.label}</option>)}
          </Select>
          {gone && <p className="text-xs text-warn">{t("channelGoneHint")}</p>}
        </div>
      );
    }
    if (f.kind === "choice") {
      return <Select value={value} onChange={(e) => set(f.key, e.target.value)}>{f.choices!.map((c) => <option key={c} value={c}>{t(`choice.${f.key}.${c}`)}</option>)}</Select>;
    }
    if (f.kind === "weekdays") {
      return (
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {WEEKDAYS.map((d) => (
            <Checkbox key={d} label={t(`day.${d}`)} checked={weekdays.includes(d)}
              onChange={(e) => set(f.key, WEEKDAYS.filter((x) => (x === d ? e.target.checked : weekdays.includes(x))).join(","))} />
          ))}
        </div>
      );
    }
    if (f.kind === "text") return <Input value={value} maxLength={200} onChange={(e) => set(f.key, e.target.value)} />;
    return <NumberInput value={value} inputMode={f.kind === "integer" ? "numeric" : "decimal"} onChange={(v) => set(f.key, v)} />;
  };

  // Settings of a unit that is off never show; the rarely changed groups sit behind "More options".
  const needs: Record<string, string> = { people: "people", alerts: "intel" };
  const shown = GROUPS.filter((g) => !needs[g.id] || enabledUnits.has(needs[g.id]));
  const card = (g: (typeof GROUPS)[number]) => (
    <Card key={g.id} title={t(`group.${g.id}`)} description={t(`groupHint.${g.id}`)}>
      <div className="divide-y divide-line">
        {g.fields.map((f) => (
          <div key={f.key} className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[1fr_minmax(0,20rem)] sm:items-center sm:gap-6">
            <div>
              <p className="text-sm font-medium">{t(`set.${f.key}`)}{f.kind === "money" && currency ? ` (${currency})` : ""}</p>
              <p className="text-xs text-muted">{t(`setHint.${f.key}`)}</p>
            </div>
            <Field label={t(`set.${f.key}`)} className="[&>label]:sr-only">{control(f)}</Field>
          </div>
        ))}
      </div>
      {g.id === "files" && <FilesUsage companyId={companyId} />}
    </Card>
  );
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {shown.filter((g) => !RARE.includes(g.id)).map(card)}
      <details className="group rounded-xl border border-line bg-surface">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
          {t("moreOptions")}<span aria-hidden className="ml-1 inline-block text-xs text-muted transition-transform group-open:rotate-90">›</span>
        </summary>
        <div className="space-y-4 border-t border-line p-4">{shown.filter((g) => RARE.includes(g.id)).map(card)}</div>
      </details>
      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center justify-end gap-2 bg-bg/90 py-3 pl-1 pr-20 sm:pr-36 backdrop-blur">
        {dirty && <span className="text-xs text-muted">{t("unsaved")}</span>}
        <Button type="button" variant="secondary" disabled={!dirty} onClick={() => settings.data && setForm(toForm(settings.data))}>{t("discard")}</Button>
        <Button type="submit" loading={save.isPending} disabled={!dirty}>{t("save")}</Button>
      </div>
    </form>
  );
}

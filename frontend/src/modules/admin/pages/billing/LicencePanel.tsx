import { Copy } from "lucide-react";
import { useRef, useState } from "react";

import { api, Alert, Badge, Button, Card, DetailList, ErrorState, ErrorText, Field, formatDate, PageHeader, Skeleton, Textarea, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { licenceTone } from "./lib";
import { UsageCard } from "./UsageCard";

const KEY = ["billing-licence"];

/** Self-hosted copies: what the installed licence allows, and where to put a new or renewed licence file. */
export function LicencePanel({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/api/v1/billing/licence")) });
  const [text, setText] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const install = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/licence", { body: { file: text.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: KEY }); void qc.invalidateQueries({ queryKey: ["billing-plan"] }); setText(""); toast(t("billing.licenceInstalled"), "ok"); },
    meta: { silent: true },
  });
  const copy = (id: string) => { void navigator.clipboard?.writeText(id).then(() => toast(t("billing.copied"), "ok"), () => toast(t("billing.copyFailed"), "bad")); };
  const choose = async (f: File | undefined) => { if (f) { install.reset(); setText(await f.text()); } };

  if (q.error) return <ErrorState title={t("billing.loadFailed")} message={q.error.message} onRetry={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-48 w-full" />;
  const l = q.data;
  const ent = (l.entitlements ?? {}) as { edition?: string; units?: string[] | null };
  return (
    <>
      <PageHeader title={t("billing.licenceTitle")} description={t("billing.licenceHint")} />
      {l.renewal_due && <Alert tone="warn" className="mb-4">{t("billing.renewalDue")}</Alert>}
      {l.message && <Alert tone={licenceTone(l.status) === "ok" ? "ok" : licenceTone(l.status) === "warn" ? "warn" : "bad"} className="mb-4">{l.message}</Alert>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("billing.licenceCard")} actions={<Badge tone={licenceTone(l.status)}>{t(`billing.licenceState.${l.status}`, { defaultValue: l.status })}</Badge>}>
          {!l.installed ? <p className="text-sm text-muted">{t("billing.noLicence")}</p> : (
            <DetailList items={[
              { label: t("billing.customer"), value: l.customer ?? "—" },
              { label: t("billing.licenceNo"), value: l.licence_no ?? "—" },
              { label: t("billing.edition"), value: ent.edition ?? "—" },
              { label: t("billing.validUntil"), value: l.valid_until ? formatDate(l.valid_until) : t("billing.perpetual") },
              ...(l.days_left !== null && l.days_left !== undefined ? [{ label: t("billing.daysLeft"), value: String(l.days_left) }] : []),
              ...(l.update_until ? [{ label: t("billing.updatesUntil"), value: formatDate(l.update_until) }] : []),
            ]} />
          )}
          {l.updates_ended && <p className="mt-3 text-sm text-warn">{t("billing.updatesEnded")}</p>}
          <div className="mt-4 border-t border-line pt-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">{t("billing.instanceId")}</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded bg-sunken px-2 py-1 text-xs">{l.instance_id}</code>
              <Button size="sm" variant="secondary" onClick={() => copy(l.instance_id)} aria-label={t("billing.copyInstance")}><Copy className="h-4 w-4" /></Button>
            </div>
            <p className="mt-1 text-xs text-muted">{t("billing.instanceHint")}</p>
          </div>
        </Card>
        {l.usage && <UsageCard plan={{ usage: l.usage, units_in_plan: ent.units ?? null, units_over_plan: [] }} />}
      </div>
      {canManage && (
        <div className="mt-4">
          <Card title={t("billing.installTitle")} description={t("billing.installHint")}>
            <div className="space-y-3">
              <Field label={t("billing.licenceFile")}>
                <Textarea rows={5} value={text} onChange={(e) => { install.reset(); setText(e.target.value); }} spellCheck={false} className="font-mono text-xs" />
              </Field>
              <ErrorText>{install.error?.message}</ErrorText>
              <div className="flex flex-wrap gap-2">
                <input ref={file} type="file" className="sr-only" aria-label={t("billing.chooseFile")} onChange={(e) => { void choose(e.target.files?.[0]); e.target.value = ""; }} />
                <Button variant="secondary" onClick={() => file.current?.click()}>{t("billing.chooseFile")}</Button>
                <Button loading={install.isPending} disabled={text.trim().length < 10} onClick={() => install.mutate()}>{t("billing.installButton")}</Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

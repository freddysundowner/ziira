import { Fragment, useState } from "react";

import { api, Alert, Badge, type BadgeTone, Button, Card, ErrorState, SkeletonRows, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { countByStatus } from "../logic";

const TONE: Record<string, BadgeTone> = { draft: "neutral", submitted: "info", approved: "ok", rejected: "bad" };

/** The WhatsApp message templates: which the provider has approved. WhatsApp may start a conversation only with an approved template;
 *  until then the message goes by the person's next channel. */
export default function TemplatesTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["leadsintel-templates", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/notifications/templates", { params: { query: { company_id: companyId } } })),
  });
  const done = (counts: Record<string, number>) => {
    void qc.invalidateQueries({ queryKey: ["leadsintel-templates"] });
    toast(Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${t(`status.${k}`, { defaultValue: k })}`).join(", ") || t("nothingToDo"), "ok");
  };
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/templates/submit", { body: { company_id: companyId } })),
    onSuccess: (r) => done(r.counts),
  });
  const sync = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/templates/sync", { body: { company_id: companyId } })),
    onSuccess: (r) => done(r.counts),
  });
  if (list.error) return <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />;
  if (!list.data) return <SkeletonRows rows={6} cols={4} />;
  const counts = countByStatus(list.data);
  return (
    <Card title={t("templatesTitle")} description={t("templatesHint")}
      actions={<div className="flex gap-2"><Button size="sm" loading={submit.isPending} onClick={() => submit.mutate()}>{t("submitAll")}</Button><Button size="sm" variant="secondary" loading={sync.isPending} onClick={() => sync.mutate()}>{t("checkStatus")}</Button></div>}>
      <p className="mb-3 flex flex-wrap gap-2 text-xs">
        {(["approved", "submitted", "draft", "rejected"] as const).map((s) => <Badge key={s} tone={TONE[s]}>{counts[s]} {t(`status.${s}`)}</Badge>)}
      </p>
      {(submit.error || sync.error) && <Alert tone="bad" className="mb-3">{(submit.error ?? sync.error)?.message}</Alert>}
      <ul className="divide-y divide-line">
        {list.data.map((row) => (
          <Fragment key={row.id}>
            <li className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <button type="button" className="min-w-0 text-left" onClick={() => setOpen(open === row.id ? null : row.id)} aria-expanded={open === row.id}>
                <span className="font-medium">{t(`template.${row.code}`, { defaultValue: row.code })}</span>
                <span className="ml-2 text-xs text-muted uppercase">{row.language}</span>
              </button>
              <Badge tone={TONE[row.status] ?? "neutral"}>{t(`status.${row.status}`, { defaultValue: row.status })}</Badge>
            </li>
            {open === row.id && (
              <li className="pb-3 text-sm text-muted">
                <p className="rounded-lg bg-sunken p-3">{row.body}</p>
                {row.rejection_reason && <p className="mt-2 text-bad">{row.rejection_reason}</p>}
              </li>
            )}
          </Fragment>
        ))}
      </ul>
    </Card>
  );
}

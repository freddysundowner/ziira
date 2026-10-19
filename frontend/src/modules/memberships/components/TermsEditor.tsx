import { useState } from "react";

import { api, Alert, Badge, Button, Card, ErrorState, Field, formatDate, Input, Skeleton, Textarea, toast, unwrap, useCan, useCompany, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

/** The terms members accept. Publishing makes a new version; earlier versions and who accepted them are kept. */
export function TermsEditor() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const canEdit = useCan("memberships.plans");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const q = useQuery({
    enabled: !!company, queryKey: ["memberships", "waiver-versions", company?.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/waiver/versions", { params: { query: { company_id: company?.id ?? "" } } })),
  });
  const publish = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/waiver/versions", { body: { company_id: company?.id ?? "", title: title.trim(), body: body.trim() } })),
    onSuccess: (v) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t("waiver.published", { version: v.version }), "ok"); setTitle(""); setBody(""); },
  });
  if (q.error) return <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />;
  if (!q.data) return <Skeleton className="h-48 w-full" />;
  const versions = [...q.data].sort((a, b) => b.version - a.version);
  const current = versions[0];
  return (
    <div className="space-y-4">
      <Card title={t("waiver.editorTitle")} description={t("waiver.editorHint")}>
        {current ? <p className="mb-3 text-sm">{t("waiver.current", { version: current.version, title: current.title })}</p> : <Alert tone="warn" className="mb-3">{t("waiver.noneYet")}</Alert>}
        {canEdit ? (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); publish.mutate(); }}>
            <Field label={t("waiver.titleLabel")} required><Input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field>
            <Field label={t("waiver.bodyLabel")} hint={t("waiver.bodyHint")} required><Textarea rows={10} maxLength={20000} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
            <div className="flex justify-end"><Button type="submit" loading={publish.isPending} disabled={!title.trim() || !body.trim()}>{t("waiver.publish")}</Button></div>
          </form>
        ) : <Alert tone="info">{t("policiesReadOnly")}</Alert>}
      </Card>
      {versions.length > 0 && (
        <Card title={t("waiver.history")} flush>
          <ul className="divide-y divide-line">
            {versions.map((v) => (
              <li key={v.id} className="px-4 py-3">
                <details>
                  <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm font-medium"><Badge tone={v.id === current?.id ? "ok" : "neutral"}>{t("waiver.version", { version: v.version })}</Badge>{v.title}<span className="font-normal text-muted">{formatDate(v.created_at)}</span></summary>
                  <div className="mt-2 whitespace-pre-wrap rounded-lg bg-sunken p-3 text-sm">{v.body}</div>
                </details>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

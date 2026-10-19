import { Check, Circle } from "lucide-react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Card, ErrorState, Skeleton, Switch, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { usePackSteps } from "../hooks";

/** The first-run checklist an industry pack gave, and the sample week it can fill the business with (and take away again). */
export function GettingStarted({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const steps = usePackSteps(companyId);
  const sample = useQuery({ queryKey: ["jobs", "sample", companyId], enabled: !!companyId, queryFn: () => unwrap(api.GET("/api/v1/jobs/sample-data", { params: { query: { company_id: companyId } } })) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["jobs"] }); };
  const load = useMutation({ mutationFn: () => unwrap(api.POST("/api/v1/jobs/sample-data", { params: { query: { company_id: companyId } } })), onSuccess: () => { refresh(); toast(t("garage.start.loaded"), "ok"); } });
  const remove = useMutation({ mutationFn: () => unwrap(api.DELETE("/api/v1/jobs/sample-data", { params: { query: { company_id: companyId } } })), onSuccess: () => { refresh(); toast(t("garage.start.removed"), "ok"); } });
  const hide = useMutation({ mutationFn: (hidden: boolean) => unwrap(api.POST("/api/v1/jobs/pack-steps/hide", { params: { query: { company_id: companyId, hidden } } })), onSuccess: refresh });
  const tick = useMutation({ mutationFn: (v: { id: string; done: boolean }) => unwrap(api.POST("/api/v1/jobs/pack-steps/{step_id}/done", { params: { path: { step_id: v.id }, query: { done: v.done } } })), onSuccess: refresh });
  if (steps.error) return <ErrorState title={t("garage.start.loadFailed")} message={steps.error.message} onRetry={() => void steps.refetch()} />;
  if (!steps.data || !sample.data) return <Skeleton className="h-48" />;
  const list = steps.data;
  const hidden = list.length > 0 && list.every((s) => s.hidden);
  return (
    <div className="space-y-4">
      <Card title={t("garage.start.title")} description={t("garage.start.hint")}>
        {list.length === 0 ? <p className="text-sm text-muted">{t("garage.start.none")}</p> : (
          <>
            <ul className="divide-y divide-line">
              {list.map((s) => (
                <li key={s.id} className="flex items-start gap-3 py-3">
                  {s.done ? <Check className="mt-0.5 h-5 w-5 shrink-0 text-ok" aria-label={t("garage.start.done")} /> : <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-label={t("garage.start.todo")} />}
                  <div className="min-w-0 flex-1">
                    <p className={s.done ? "text-sm text-muted line-through" : "text-sm font-medium"}>{s.title}</p>
                    {s.hint && <p className="text-xs text-muted">{s.hint}</p>}
                  </div>
                  {!s.done && s.to_path && <Link to={s.to_path}><Button size="sm" variant="secondary">{t("garage.start.open")}</Button></Link>}
                  {!s.check_key && <Button size="sm" variant="ghost" onClick={() => tick.mutate({ id: s.id, done: !s.done })}>{s.done ? t("garage.start.untick") : t("garage.start.tick")}</Button>}
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center gap-2 text-sm"><Switch checked={hidden} onChange={(v) => hide.mutate(v)} label={t("garage.start.hide")} /><span>{t("garage.start.hide")}</span></div>
          </>
        )}
      </Card>
      {sample.data.available && (
        <Card title={t("garage.start.sample")} description={sample.data.note ?? undefined}>
          <div className="space-y-3">
            <p className="text-sm text-muted">{t("garage.start.sampleHint")}</p>
            {sample.data.loaded ? (
              <>
                <Alert tone="info">{t("garage.start.sampleLoaded")}</Alert>
                <Button variant="secondary" loading={remove.isPending} onClick={() => remove.mutate()}>{t("garage.start.sampleRemove")}</Button>
              </>
            ) : <Button loading={load.isPending} onClick={() => load.mutate()}>{t("garage.start.sampleLoad")}</Button>}
          </div>
        </Card>
      )}
    </div>
  );
}

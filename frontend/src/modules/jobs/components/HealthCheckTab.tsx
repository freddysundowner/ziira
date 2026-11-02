import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, cx, EmptyState, Input, Skeleton, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { inspectionSections } from "../lib";
import type { Job } from "../types";

const RATINGS = ["green", "amber", "red", "na"] as const;
const TONE = { green: "bg-ok-soft text-ok", amber: "bg-warn-soft text-warn", red: "bg-bad-soft text-bad", na: "bg-sunken text-ink" } as const;

/** The vehicle health check: each thing looked at is marked green (good), amber (soon) or red (now), with a note. */
export function HealthCheckTab({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const key = ["jobs", "inspection", job.id];
  const path = { params: { path: { job_id: job.id } } };
  const [section, setSection] = useState("");
  const [label, setLabel] = useState("");
  const check = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs/{job_id}/inspection", path)) });
  const done = (fresh: unknown) => { qc.setQueryData(key, fresh); void qc.invalidateQueries({ queryKey: ["jobs", "job", job.id] }); };
  const begin = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/inspection/start", path)), onSuccess: done, onError: (e) => toast(e.message, "bad") });
  const change = useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; rating?: (typeof RATINGS)[number] | "pending"; note?: string }) =>
      unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}/inspection/items/{item_id}", { params: { path: { job_id: job.id, item_id: v.id } }, body: { rating: v.rating, note: v.note } })),
    onSuccess: done, onError: (e) => toast(e.message, "bad"),
  });
  const add = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/inspection/items", { ...path, body: { section: section.trim(), label: label.trim() } })),
    onSuccess: (fresh) => { done(fresh); setLabel(""); }, onError: (e) => toast(e.message, "bad"),
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/jobs/jobs/{job_id}/inspection/items/{item_id}", { params: { path: { job_id: job.id, item_id: id } } })),
    onSuccess: done, onError: (e) => toast(e.message, "bad"),
  });
  if (!check.data) return <Skeleton className="mt-4 h-64" />;
  const c = check.data;
  if (!c.started) {
    return (
      <div className="mt-4">
        <EmptyState title={t("floor.health.empty")} hint={t("floor.health.emptyHint")}
          action={editable ? <Button loading={begin.isPending} onClick={() => begin.mutate()}>{t("floor.health.start")}</Button> : undefined} />
      </div>
    );
  }
  return (
    <div className="mt-4 space-y-4">
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label={t("floor.health.counts")}>
        <span className="font-medium text-bad">{t("floor.health.red", { count: c.red })}</span>
        <span className="font-medium text-warn">{t("floor.health.amber", { count: c.amber })}</span>
        <span className="font-medium text-ok">{t("floor.health.green", { count: c.green })}</span>
        {c.pending > 0 && <span className="text-muted">{t("floor.health.pending", { count: c.pending })}</span>}
      </p>
      {inspectionSections(c.items).map((group) => (
        <Card key={group.section} title={group.section}>
          <ul className="divide-y divide-line">
            {group.items.map((item) => (
              <li key={item.id} className="space-y-2 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium">{item.label}</span>
                  <div role="group" aria-label={item.label} className="inline-flex gap-1">
                    {RATINGS.map((r) => (
                      <button key={r} type="button" disabled={!editable || change.isPending} aria-pressed={item.rating === r}
                        onClick={() => change.mutate({ id: item.id, rating: item.rating === r ? "pending" : r })}
                        className={cx("h-8 rounded-md px-2.5 text-xs font-medium disabled:cursor-not-allowed", item.rating === r ? TONE[r] : "border border-line text-muted hover:bg-sunken")}>{t(`floor.health.rating.${r}`)}</button>
                    ))}
                  </div>
                </div>
                {(item.rating === "amber" || item.rating === "red" || item.note) && (
                  <Input key={item.note ?? ""} aria-label={t("floor.health.note")} placeholder={t("floor.health.notePlaceholder")} defaultValue={item.note ?? ""} maxLength={500} disabled={!editable}
                    onBlur={(e) => { if (e.target.value.trim() !== (item.note ?? "")) change.mutate({ id: item.id, note: e.target.value.trim() }); }} />
                )}
                {editable && item.rating === "pending" && (
                  <button type="button" className="text-xs text-muted hover:text-bad" onClick={() => remove.mutate(item.id)}>{t("floor.health.remove")}</button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ))}
      {editable && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (section.trim() && label.trim()) add.mutate(); }}>
          <Input aria-label={t("floor.health.section")} placeholder={t("floor.health.section")} className="w-40" maxLength={80} value={section} onChange={(e) => setSection(e.target.value)} />
          <Input aria-label={t("floor.health.line")} placeholder={t("floor.health.line")} className="min-w-48 flex-1" maxLength={160} value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button type="submit" variant="secondary" loading={add.isPending} disabled={!section.trim() || !label.trim()}><Plus className="h-4 w-4" />{t("common.add")}</Button>
        </form>
      )}
      <p className="text-xs text-muted">{t("floor.health.customerSees")}</p>
    </div>
  );
}

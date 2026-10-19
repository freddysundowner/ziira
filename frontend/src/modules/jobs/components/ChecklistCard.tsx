import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, cx, Input, unwrap, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import type { Job } from "../types";

const STATES = ["ok", "issue", "na"] as const;
const TONE = { ok: "bg-ok-soft text-ok", issue: "bg-bad-soft text-bad", na: "bg-sunken text-ink" } as const;

/** The checks done on the item: each line is ok, an issue, or not applicable, with a note. */
export function ChecklistCard({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const [label, setLabel] = useState("");
  const change = useJobAction(job.id, (v: { id: string; state?: string; note?: string }) =>
    unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}/checklist/{item_id}", { params: { path: { job_id: job.id, item_id: v.id } }, body: { state: v.state as never, note: v.note } })));
  const add = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/checklist", { params: { path: { job_id: job.id } }, body: { label: label.trim() } })), { onDone: () => setLabel("") });
  if (job.checklist.length === 0 && !editable) return null;
  return (
    <Card title={t("checklist.title")}>
      {job.checklist.length === 0 && <p className="mb-3 text-sm text-muted">{t("checklist.empty")}</p>}
      <ul className="divide-y divide-line">
        {job.checklist.map((item) => (
          <li key={item.id} className="space-y-2 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{item.label}</span>
              <div role="group" aria-label={item.label} className="inline-flex gap-1">
                {STATES.map((s) => (
                  <button key={s} type="button" disabled={!editable || change.isPending} aria-pressed={item.state === s}
                    onClick={() => change.mutate({ id: item.id, state: item.state === s ? "pending" : s })}
                    className={cx("h-8 rounded-md px-2.5 text-xs font-medium disabled:cursor-not-allowed", item.state === s ? TONE[s] : "border border-line text-muted hover:bg-sunken")}>{t(`checklist.state.${s}`)}</button>
                ))}
              </div>
            </div>
            {(item.state === "issue" || item.note) && (
              <Input key={item.note ?? ""} aria-label={t("checklist.note")} placeholder={t("checklist.note")} defaultValue={item.note ?? ""} maxLength={500} disabled={!editable}
                onBlur={(e) => { if (e.target.value.trim() !== (item.note ?? "")) change.mutate({ id: item.id, note: e.target.value.trim() }); }} />
            )}
          </li>
        ))}
      </ul>
      {editable && (
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (label.trim()) add.mutate(); }}>
          <Input aria-label={t("checklist.add")} placeholder={t("checklist.add")} maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button type="submit" variant="secondary" loading={add.isPending} disabled={!label.trim()}><Plus className="h-4 w-4" />{t("common.add")}</Button>
        </form>
      )}
    </Card>
  );
}

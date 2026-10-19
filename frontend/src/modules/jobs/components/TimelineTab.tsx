import { ArrowRight } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, EmptyState, formatDate, humanise, Textarea, unwrap, useCan, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import type { Job } from "../types";

/** What happened to the job, newest first, and a box to add a note (notes are allowed even on a locked job). */
export function TimelineTab({ job }: { job: Job }) {
  const { t } = useTranslation("jobs");
  const canNote = useCan("jobs.manage");
  const [text, setText] = useState("");
  const add = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/notes", { params: { path: { job_id: job.id } }, body: { text: text.trim() } })), { done: t("timeline.noteAdded"), onDone: () => setText("") });
  const events = [...job.events].reverse();
  return (
    <div className="space-y-4">
      {canNote && (
        <Card title={t("timeline.addNote")}>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate(); }}>
            <Textarea aria-label={t("timeline.addNote")} placeholder={t("timeline.notePlaceholder")} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
            <div className="flex justify-end"><Button type="submit" loading={add.isPending} disabled={!text.trim()}>{t("timeline.saveNote")}</Button></div>
          </form>
        </Card>
      )}
      <Card title={t("timeline.title")} flush>
        {events.length === 0 ? <EmptyState title={t("timeline.empty")} /> : (
          <ol className="divide-y divide-line">
            {events.map((e) => (
              <li key={e.id} className="px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5">
                  <span className="font-medium">{t(`timeline.kind.${e.kind}`, { defaultValue: humanise(e.kind) })}</span>
                  <span className="text-xs text-muted">{[e.by, formatDate(e.created_at, true)].filter(Boolean).join(" · ")}</span>
                </div>
                {e.kind === "status" && e.to_status && (
                  <p className="mt-0.5 inline-flex items-center gap-1.5 text-muted">{e.from_status ?? "—"}<ArrowRight className="h-3.5 w-3.5" aria-label={t("timeline.to")} />{e.to_status}</p>
                )}
                {e.note && <p className="mt-0.5 whitespace-pre-line text-muted">{e.note}</p>}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

import { FilePlus2, PenLine } from "lucide-react";
import { useState } from "react";

import { api, Button, EmptyState, unwrap, useCan, useTranslation } from "@/sdk";

import { useEstimateAction } from "../hooks";
import { liveLines } from "../lib";
import type { Estimate, Job } from "../types";
import { DecideDialog } from "./DecideDialog";
import { EstimateCard } from "./EstimateCard";
import { EstimateEditor } from "./EstimateEditor";
import { SendEstimateDialog } from "./SendEstimateDialog";

/** The estimates (quotes) of a job, newest version first. The customer approves through a link, or staff record the answer. */
export function EstimatesTab({ job, currency, editable }: { job: Job; currency: string | undefined; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const canAct = useCan("jobs.estimate") && editable;
  const [editing, setEditing] = useState<Estimate | null | "new">(null);
  const [sending, setSending] = useState<Estimate | null>(null);
  const [deciding, setDeciding] = useState<{ estimate: Estimate; approve: boolean } | null>(null);
  const draft = job.estimates.some((e) => e.status === "draft");
  const hasLines = liveLines(job.parts).length + liveLines(job.labour).length > 0;
  const fromJob = useEstimateAction(() => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/estimates", { params: { path: { job_id: job.id } }, body: { from_job: true, kind: "main" } })), { done: t("estimates.saved") });
  const approved = job.estimates.some((e) => e.status === "approved") && !job.claim;
  const extra = useEstimateAction(() => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/estimates", { params: { path: { job_id: job.id } }, body: { from_job: true, kind: "additional" } })), { done: t("estimates.saved") });
  const versions = [...job.estimates].sort((a, b) => b.version - a.version);
  const editorEstimate = editing && editing !== "new" ? editing : null;

  return (
    <div className="space-y-4">
      {canAct && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={draft || !hasLines} loading={fromJob.isPending} onClick={() => fromJob.mutate(undefined)}><FilePlus2 className="h-4 w-4" />{t("estimates.fromJob")}</Button>
          <Button variant="secondary" disabled={draft} onClick={() => setEditing("new")}><PenLine className="h-4 w-4" />{t("estimates.byHand")}</Button>
          {approved && <Button variant="secondary" disabled={draft} loading={extra.isPending} onClick={() => extra.mutate(undefined)}><FilePlus2 className="h-4 w-4" />{t("garage.estimates.additional")}</Button>}
          {draft && <p className="text-sm text-muted">{t("estimates.oneDraft")}</p>}
        </div>
      )}
      {versions.length === 0 ? <EmptyState title={t("estimates.empty")} hint={canAct ? t("estimates.emptyHint") : undefined} /> : versions.map((e) => (
        <EstimateCard key={e.id} estimate={e} currency={currency} canAct={canAct} onEdit={() => setEditing(e)} onSend={() => setSending(e)} onDecide={(approve) => setDeciding({ estimate: e, approve })} />
      ))}
      <EstimateEditor jobId={job.id} estimate={editorEstimate} open={editing !== null} onClose={() => setEditing(null)} currency={currency} />
      <SendEstimateDialog estimate={sending} onClose={() => setSending(null)} />
      <DecideDialog estimate={deciding?.estimate ?? null} approve={deciding?.approve ?? true} customerName={job.customer_name ?? ""} onClose={() => setDeciding(null)} />
    </div>
  );
}

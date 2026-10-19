import { Check, Clock, FilePlus2, PenLine, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { claimHref } from "@/modules/claims/public";
import { Alert, api, Badge, Button, Card, Field, Input, Modal, money, quantity, Textarea, unwrap, useCan, useMutation, useTranslation } from "@/sdk";

import { useJobAction, useRefreshJobs } from "../hooks";
import type { Job } from "../types";

const TONE = { approved: "ok", countered: "warn", rejected: "bad", needs_information: "warn", pending: "neutral" } as const;

/**
 * What the insurer (or fleet owner) has said about the work on this job: each line approved, countered, rejected or still
 * asked. A technician sees only the work that is authorised, without prices. Staff can draft the payer's estimate from the
 * job's own parts and labour, and write down who signed the finished work off.
 */
export function ClaimWork({ job, currency }: { job: Job; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const navigate = useNavigate();
  const refresh = useRefreshJobs();
  const canEstimate = useCan("jobs.estimate");
  const canManage = useCan("jobs.manage");
  const canSeeClaims = useCan("claims.view");
  const [signing, setSigning] = useState(false);
  const [by, setBy] = useState("");
  const [note, setNote] = useState("");
  const claim = job.claim;
  const draft = useMutation({
    mutationFn: (kind: "original" | "supplementary") => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/claim/estimate", { params: { path: { job_id: job.id } }, body: { kind } })),
    onSuccess: () => { void refresh(); if (claim) navigate(claimHref(claim.id)); },
  });
  const sign = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/claim/complete", { params: { path: { job_id: job.id } }, body: { signed_by: by.trim(), note: note.trim() || null } })),
    { done: t("garage.claim.signedOff"), onDone: () => setSigning(false) });
  if (!claim) return null;
  const full = !claim.limited;
  const open = claim.status !== "closed" && claim.status !== "invoiced" && claim.status !== "settled";
  return (
    <Card title={t("garage.claim.title")} description={t("garage.claim.payer", { name: claim.payer_name })}
      actions={full && open && canEstimate && (
        <Button size="sm" variant="secondary" loading={draft.isPending} onClick={() => draft.mutate(claim.status === "draft" ? "original" : "supplementary")}>
          <FilePlus2 className="h-4 w-4" />{claim.status === "draft" ? t("garage.claim.draftEstimate") : t("garage.claim.draftExtra")}
        </Button>
      )}>
      {/* people who see the claim panel already read this message there; a technician has no panel */}
      {claim.gate && claim.status !== "closed" && !canSeeClaims && <Alert tone={claim.gate.allowed ? "warn" : "bad"} className="mb-3">{claim.gate.message}</Alert>}
      {claim.lines.length === 0 ? <p className="text-sm text-muted">{claim.limited ? t("garage.claim.nothingAuthorised") : t("garage.claim.noLines")}</p> : (
        <ul className="divide-y divide-line text-sm">
          {claim.lines.map((l) => (
            <li key={l.id} className="flex items-start justify-between gap-3 py-2">
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{l.description}</span>
                  {!claim.limited && <Badge tone={TONE[l.state as keyof typeof TONE] ?? "neutral"}>{t(`garage.claim.state.${l.state}`, { defaultValue: l.state })}</Badge>}
                  {l.part_class && <Badge tone="neutral">{t(`garage.parts.classes.${l.part_class}`)}</Badge>}
                </span>
                <span className="tnum block text-xs text-muted">{quantity(l.quantity)}{l.reason ? ` · ${l.reason}` : ""}{l.waiting_on ? ` · ${t(`garage.claim.waitingOn.${l.waiting_on}`)}` : ""}</span>
              </span>
              <span className="flex shrink-0 flex-col items-end text-right">
                {l.work_authorised ? <span className="inline-flex items-center gap-1 text-ok"><Check className="h-4 w-4" aria-hidden />{t("garage.claim.goAhead")}</span>
                  : l.state === "rejected" || (l.state === "countered") ? <span className="inline-flex items-center gap-1 text-bad"><X className="h-4 w-4" aria-hidden />{t("garage.claim.hold")}</span>
                  : <span className="inline-flex items-center gap-1 text-muted"><Clock className="h-4 w-4" aria-hidden />{t("garage.claim.wait")}</span>}
                {full && l.payer_pays != null && <span className="tnum text-xs text-muted">{t("garage.claim.payerPays", { amount: money(l.payer_pays, currency) })}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {full && claim.authority_ref && <p className="mt-3 text-sm text-muted">{t("garage.claim.authority", { ref: claim.authority_ref })}</p>}
      {full && open && canManage && !claim.completed && claim.status !== "draft" && (
        <div className="mt-3"><Button size="sm" variant="secondary" onClick={() => setSigning(true)}><PenLine className="h-4 w-4" />{t("garage.claim.signOff")}</Button></div>
      )}
      {claim.completed && <p className="mt-3 text-sm text-ok">{t("garage.claim.done")}</p>}
      <Modal open={signing} onClose={() => setSigning(false)} title={t("garage.claim.signOff")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setSigning(false)}>{t("common.cancel")}</Button><Button loading={sign.isPending} disabled={!by.trim()} onClick={() => sign.mutate(undefined)}>{t("garage.claim.signOff")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("garage.claim.signHint")}</p>
          <Field label={t("garage.claim.signedBy")} required><Input maxLength={160} value={by} onChange={(e) => setBy(e.target.value)} /></Field>
          <Field label={t("collect.note")}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>
    </Card>
  );
}

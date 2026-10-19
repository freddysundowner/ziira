import { FilePlus2, Pencil, Receipt, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, api, Button, Field, Input, Modal, money, Select, Textarea, unwrap, useCan, useMutation, useTranslation } from "@/sdk";

import { useJobAction, useRefreshJobs } from "../hooks";
import { isCollect, nextStages } from "../lib";
import { jobHref } from "../public";
import type { Job, Stage } from "../types";
import { EditJobDrawer } from "./EditJobDrawer";
import { useStageMover } from "./StageMover";

/** What can be done to a job right now: move it on, collect, invoice, edit, start a return visit. */
export function JobActions({ job, workflow, currency }: { job: Job; workflow: readonly Stage[]; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const canManage = useCan("jobs.manage");
  const canInvoice = useCan("jobs.invoice");
  const mover = useStageMover();
  const [editing, setEditing] = useState(false);
  const [invoicing, setInvoicing] = useState(false);
  const [visiting, setVisiting] = useState(false);
  const next = nextStages(workflow, job.next_status_ids);
  const collect = next.find(isCollect);
  const [payNow, setPayNow] = useState("");
  const [payRef, setPayRef] = useState("");
  const invoice = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/invoice", { params: { path: { job_id: job.id } }, body: {
    pay_method: (payNow || null) as "cash" | "mobile_money" | "bank" | "card" | null, pay_reference: payRef.trim() || null } })), { done: t("invoice.done"), onDone: () => setInvoicing(false) });
  const throughClaim = !!job.claim && job.claim.status !== "closed";
  const target = { id: job.id, number: job.number, title: job.title };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canManage && next.filter((s) => !isCollect(s)).map((s) => <Button key={s.id} variant="secondary" loading={mover.busy} onClick={() => mover.move(target, s)}>{s.name}</Button>)}
      {canManage && collect && <Button onClick={() => mover.collect(target)}>{t("actions.collect")}</Button>}
      {canInvoice && job.can_invoice && <Button variant="secondary" onClick={() => setInvoicing(true)}><Receipt className="h-4 w-4" />{t("actions.invoice")}</Button>}
      {canManage && job.collected_at && <Button variant="ghost" onClick={() => setVisiting(true)}><RotateCcw className="h-4 w-4" />{t("actions.returnVisit")}</Button>}
      {canManage && !job.locked && <Button variant="ghost" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button>}
      {mover.dialog}
      <EditJobDrawer job={job} open={editing} onClose={() => setEditing(false)} />
      <Modal open={invoicing} onClose={() => setInvoicing(false)} title={t("invoice.title", { number: job.number })} size="sm"
        footer={<><Button variant="secondary" onClick={() => setInvoicing(false)}>{t("common.cancel")}</Button><Button loading={invoice.isPending} onClick={() => invoice.mutate(undefined)}>{t("invoice.confirm")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm">{throughClaim ? t("garage.invoice.claim") : t("invoice.message", { total: money(job.totals.total, currency) })}</p>
          {!job.customer_id && !throughClaim && <Alert tone="info">{t("garage.invoice.walkIn")}</Alert>}
          {!throughClaim && (
            <>
              <Field label={t("garage.invoice.payNow")} hint={t("garage.invoice.payNowHint")}>
                <Select value={payNow} onChange={(e) => setPayNow(e.target.value)}>
                  <option value="">{t("garage.invoice.onAccount")}</option>
                  {(["cash", "mobile_money", "card", "bank"] as const).map((m) => <option key={m} value={m}>{t(`garage.deposit.methods.${m}`)}</option>)}
                </Select>
              </Field>
              {payNow && payNow !== "cash" && <Field label={t("garage.deposit.reference")}><Input maxLength={60} value={payRef} onChange={(e) => setPayRef(e.target.value)} /></Field>}
            </>
          )}
        </div>
      </Modal>
      <ReturnVisitDialog job={job} open={visiting} onClose={() => setVisiting(false)} />
    </div>
  );
}

/** A new job for the same customer and item, linked to this one (warranty rework). */
function ReturnVisitDialog({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const navigate = useNavigate();
  const refresh = useRefreshJobs();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/return-visit", { params: { path: { job_id: job.id } }, body: { title: title.trim() || null, description: description.trim() || null } })),
    onSuccess: (visit) => { void refresh(); onClose(); navigate(jobHref(visit.id)); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("returnVisit.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={start.isPending} onClick={() => start.mutate()}><FilePlus2 className="h-4 w-4" />{t("returnVisit.start")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("returnVisit.hint", { number: job.number })}</p>
        <Field label={t("receive.title")} hint={t("returnVisit.titleHint")}><Input maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label={t("receive.details")}><Textarea maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

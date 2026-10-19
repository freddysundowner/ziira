import { CirclePause, CirclePlay, Pencil, Play, Square } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Badge, Button, ConfirmDialog, DetailList, Drawer, Field, formatDate, Input, Modal, money, toast, today, unwrap, useCan, useCurrency, useMutation,
  useQueryClient, useTranslation,
} from "@/sdk";

import type { Schedule } from "../hooks";
import { credits, runTone, scheduleTone } from "../logic";
import { RunsTable } from "./RunsTable";
import { ScheduleForm } from "./ScheduleForm";

/** One recurring invoice: what it bills, when it runs next, how the last run went, and the actions on it. */
export function ScheduleDrawer({ item, onClose }: { item: Schedule | null; onClose: () => void }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(item?.company_id);
  const canManage = useCan("recurring.manage");
  const [editing, setEditing] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [ending, setEnding] = useState(false);
  const [resumeOn, setResumeOn] = useState("");
  const path = { params: { path: { schedule_id: item?.id ?? "" } } };
  const done = (message: string) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(message, "ok"); };
  const fail = (e: unknown) => toast((e as Error).message, "bad");

  const pause = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => { done(t("schedulePaused")); setPausing(false); onClose(); },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/recurring-invoices/{schedule_id}/pause", { ...path, body: { resume_on: resumeOn || null } })) });
  const resume = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => { done(t("scheduleResumed")); onClose(); },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/recurring-invoices/{schedule_id}/resume", path)) });
  const end = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => { done(t("scheduleEnded")); setEnding(false); onClose(); },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/recurring-invoices/{schedule_id}/end", path)) });
  const run = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => { done(t("runDone")); },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/recurring-invoices/{schedule_id}/run", path)) });

  return (
    <>
      <Drawer open={!!item && !editing} onClose={onClose} title={item?.name ?? ""}
        footer={item && canManage && item.status !== "ended" ? (
          <>
            <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("edit")}</Button>
            {item.status === "active" && <Button variant="secondary" loading={run.isPending} onClick={() => run.mutate()}><Play className="h-4 w-4" />{t("runNow")}</Button>}
            {item.status === "active" && <Button variant="secondary" onClick={() => { setResumeOn(""); setPausing(true); }}><CirclePause className="h-4 w-4" />{t("pause")}</Button>}
            {item.status === "paused" && <Button variant="secondary" loading={resume.isPending} onClick={() => resume.mutate()}><CirclePlay className="h-4 w-4" />{t("resume")}</Button>}
            <Button variant="danger" onClick={() => setEnding(true)}><Square className="h-4 w-4" />{t("endSchedule")}</Button>
          </>) : undefined}>
        {item && (
          <div className="space-y-5">
            <DetailList items={[
              { label: t("customer"), value: item.customer_name ?? "—" },
              { label: t("status"), value: <Badge tone={scheduleTone(item.status)}>{t(`scheduleStatus.${item.status}`, item.status)}</Badge> },
              { label: t("repeats"), value: t("everyUnit", { count: item.interval_count, unit: t(`unit.${item.billing_interval}`), units: t(`units.${item.billing_interval}`) }) },
              { label: t("eachInvoiceLabel"), value: <span className="font-semibold">{money(item.total, currency)}</span> },
              { label: t("nextInvoice"), value: item.status === "ended" ? "—" : formatDate(item.next_run) },
              { label: t("lastInvoiceOn"), value: item.end_date ? formatDate(item.end_date) : item.max_runs ? t("afterCount", { count: item.max_runs }) : t("noEnd") },
              { label: t("whenDue"), value: item.mode === "draft" ? t("modeDraft") : t("modeIssue") },
              { label: t("lastRun"), value: item.last_run_status ? <Badge tone={runTone(item.last_run_status)}>{t(`runStatus.${item.last_run_status}`, item.last_run_status)}</Badge> : "—" },
            ]} />
            {item.last_run_status === "failed" && item.last_run_message && <Alert tone="bad">{item.last_run_message}</Alert>}
            {item.status === "paused" && item.resume_on && <Alert tone="info">{t("pausedUntil", { date: formatDate(item.resume_on) })}</Alert>}
            <div>
              <h3 className="mb-2 text-sm font-semibold">{t("invoiceLines")}</h3>
              <ul className="divide-y divide-line rounded-md border border-line text-sm">
                {item.lines.map((l, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span>{l.description || t("untitledLine")} <span className="text-muted">× {credits(l.quantity)}</span></span>
                    <span className="font-medium">{money(l.unit_price, currency)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div><h3 className="mb-2 text-sm font-semibold">{t("history")}</h3><RunsTable ownerId={item.id} companyId={item.company_id} empty={{ title: t("noRunsYet"), hint: t("noRunsYetHint") }} /></div>
          </div>
        )}
      </Drawer>
      {item && <ScheduleForm open={editing} onClose={() => { setEditing(false); onClose(); }} schedule={item} />}
      <Modal open={pausing} onClose={() => setPausing(false)} title={t("pauseTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setPausing(false)}>{t("cancel")}</Button><Button loading={pause.isPending} onClick={() => pause.mutate()}>{t("pause")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("pauseExplain")}</p>
        <Field label={t("resumeOn")} hint={t("resumeOnHint")}><Input type="date" min={today()} value={resumeOn} onChange={(e) => setResumeOn(e.target.value)} /></Field>
      </Modal>
      <ConfirmDialog open={ending} onClose={() => setEnding(false)} danger title={t("endTitle")} message={t("endExplain")} confirmLabel={t("endSchedule")}
        busy={end.isPending} onConfirm={() => end.mutate()} />
    </>
  );
}

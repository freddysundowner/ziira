import { type ReactNode, useState } from "react";

import { Alert, api, ApiError, Button, Field, Input, Modal, NumberInput, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { useRefreshJobs } from "../hooks";
import { isCollect } from "../lib";
import type { StageRef } from "../types";

interface Target {
  id: string;
  number: string;
  title: string;
}

/**
 * Moving a job to another stage, from a dragged card, a menu or a button. Collection is its own step (who took the
 * item), so moving to the stage with the "collected" role opens that question first. `dialog` must be rendered by the caller.
 */
export function useStageMover(): { move: (job: Target, to: StageRef) => void; collect: (job: Target) => void; dialog: ReactNode; busy: boolean } {
  const { t } = useTranslation("jobs");
  const refresh = useRefreshJobs();
  const [collecting, setCollecting] = useState<Target | null>(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [odometer, setOdometer] = useState("");
  const [unpaid, setUnpaid] = useState<string | null>(null);        // the server asked for a confirmation: not paid for yet

  const moveTo = useMutation({
    mutationFn: (v: { job: Target; to: StageRef }) => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/status", { params: { path: { job_id: v.job.id } }, body: { to_status_id: v.to.id, acknowledge_unpaid: false } })),
    onSuccess: (_job, v) => { void refresh(); toast(t("mover.moved", { number: v.job.number, stage: v.to.name }), "ok"); },
  });
  const collect = useMutation({
    meta: { silent: true },
    mutationFn: (v: { job: Target; confirmed: boolean }) => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/collect", { params: { path: { job_id: v.job.id } }, body: {
      collected_by_name: name.trim() || null, note: note.trim() || null, acknowledge_unpaid: v.confirmed, odometer_out: odometer === "" ? null : odometer } })),
    onSuccess: (_job, v) => { void refresh(); setCollecting(null); toast(t("mover.collected", { number: v.job.number }), "ok"); },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) setUnpaid(e.message);
      else toast((e as Error).message, "bad");
    },
  });

  const ask = (job: Target) => { setName(""); setNote(""); setOdometer(""); setUnpaid(null); setCollecting(job); };
  const close = () => setCollecting(null);
  const dialog = (
    <Modal open={collecting !== null} onClose={close} title={t("collect.title", { number: collecting?.number ?? "" })} size="sm"
      footer={<><Button variant="secondary" onClick={close}>{t("common.cancel")}</Button><Button loading={collect.isPending} variant={unpaid ? "danger" : "primary"} onClick={() => collecting && collect.mutate({ job: collecting, confirmed: unpaid !== null })}>{unpaid ? t("garage.collect.anyway") : t("collect.confirm")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("collect.hint", { title: collecting?.title ?? "" })}</p>
        <Field label={t("collect.who")}><Input value={name} maxLength={160} autoFocus onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("garage.collect.odometer")} hint={t("garage.collect.odometerHint")}><NumberInput value={odometer} onChange={setOdometer} /></Field>
        <Field label={t("collect.note")}><Input value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} /></Field>
        {unpaid && <Alert tone="warn">{unpaid}</Alert>}
      </div>
    </Modal>
  );
  return { move: (job, to) => (isCollect(to) ? ask(job) : moveTo.mutate({ job, to })), collect: ask, dialog, busy: moveTo.isPending };
}

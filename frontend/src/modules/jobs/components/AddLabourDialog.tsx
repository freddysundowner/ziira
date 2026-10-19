import { useState } from "react";

import { api, Button, Field, FormGrid, Input, Modal, NumberInput, Select, unwrap, useSession, useTranslation } from "@/sdk";

import { useJobAction, useLabourTasks, useWorkTypes } from "../hooks";
import { PersonSelect } from "./pickers";

/**
 * Record labour: a task from the flat-rate library (its standard time and, when it has one, its fixed price), or hours at a
 * rate (the work type's, else the shop's). Billed hours are what the customer pays for; booked hours are what the
 * technician really worked.
 */
export function AddLabourDialog({ jobId, companyId, open, onClose, currency }: { jobId: string; companyId: string; open: boolean; onClose: () => void; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const userId = useSession().me?.user_id ?? null;
  const tasks = useLabourTasks(companyId, true);
  const workTypes = useWorkTypes(companyId, true);
  const [task, setTask] = useState("");
  const [workType, setWorkType] = useState("");
  const [hours, setHours] = useState("");
  const [booked, setBooked] = useState("");
  const [description, setDescription] = useState("");
  const [rate, setRate] = useState("");
  const [who, setWho] = useState("");
  const library = (tasks.data ?? []).find((x) => x.code === task);
  const reset = () => { setTask(""); setWorkType(""); setHours(""); setBooked(""); setDescription(""); setRate(""); setWho(""); };
  const add = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/labour", { params: { path: { job_id: jobId } }, body: {
    task_code: task || null, work_type_code: workType || null, hours: hours === "" ? null : hours, booked_hours: booked === "" ? null : booked,
    description: description.trim() || (task ? null : t("labour.defaultDescription")), rate: rate === "" ? null : rate, assignee_id: who || userId } })),
  { done: t("labour.added"), onDone: () => { reset(); onClose(); } });
  const ready = task ? true : Number(hours) > 0;
  return (
    <Modal open={open} onClose={onClose} title={t("labour.addTitle")} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={add.isPending} disabled={!ready} onClick={() => add.mutate()}>{t("labour.add")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.labour.task")} hint={t("garage.labour.taskHint")}>
          <Select value={task} onChange={(e) => setTask(e.target.value)}>
            <option value="">{t("garage.labour.noTask")}</option>
            {(tasks.data ?? []).map((x) => <option key={x.id} value={x.code}>{x.name} · {Number(x.standard_hours)} h{x.flat_price ? ` · ${currency ?? ""} ${Number(x.flat_price)}` : ""}</option>)}
          </Select>
        </Field>
        <FormGrid>
          <Field label={t("garage.labour.workType")}>
            <Select value={workType} onChange={(e) => setWorkType(e.target.value)}>
              <option value="">{library?.work_type_code ? t("garage.labour.fromTask") : t("garage.labour.noWorkType")}</option>
              {(workTypes.data ?? []).map((w) => <option key={w.id} value={w.code}>{w.name}{w.hourly_rate ? ` (${Number(w.hourly_rate)})` : ""}</option>)}
            </Select>
          </Field>
          <Field label={t("garage.labour.billed")} required={!task}><NumberInput value={hours} onChange={setHours} placeholder={library ? String(Number(library.standard_hours)) : undefined} autoFocus /></Field>
          <Field label={t("garage.labour.booked")} hint={t("garage.labour.bookedHint")}><NumberInput value={booked} onChange={setBooked} /></Field>
          <Field label={t("labour.rate")} hint={currency ? t("labour.rateHint", { currency }) : undefined}><NumberInput value={rate} onChange={setRate} placeholder={library?.flat_price ? t("garage.labour.fixedPrice") : t("labour.rateDefault")} /></Field>
        </FormGrid>
        <Field label={t("labour.what")}><Input maxLength={300} value={description} placeholder={library?.name ?? t("labour.defaultDescription")} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label={t("garage.labour.technician")}><PersonSelect value={who} onChange={setWho} none={t("garage.labour.me")} /></Field>
      </div>
    </Modal>
  );
}

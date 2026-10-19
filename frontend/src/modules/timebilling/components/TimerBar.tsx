import { Pause, Play, Square, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { api, Button, Card, ConfirmDialog, Field, Input, Modal, Switch, toast, unwrap, useMutation, useQuery, useTranslation } from "@/sdk";

import { useRefresh, useRequestKey } from "../hooks";
import { elapsedNow, formatDuration, formatElapsed, looksForgotten, parseDuration } from "../lib";
import type { Project, Timer } from "../types";
import { ProjectPicker } from "./ProjectPicker";
import { TaskInput } from "./TaskInput";

/** The running timer: start it on a project, pause, stop (saves an entry) or throw it away. */
export function TimerBar({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const timer = useQuery<Timer | null>({
    queryKey: ["timebilling", "timer"], refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/timer")),
  });
  const asked = timer.dataUpdatedAt;
  const running = !!timer.data?.running;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);
  const seconds = timer.data ? elapsedNow(timer.data, asked, Math.max(now, asked)) : 0;

  const act = useMutation({
    mutationFn: (what: "pause" | "resume") => unwrap(api.POST(what === "pause" ? "/api/v1/timebilling/timer/pause" : "/api/v1/timebilling/timer/resume")),
    onSuccess: () => void timer.refetch(),
  });
  const discard = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/timer/discard")),
    onSuccess: () => { toast(t("timer.discarded"), "ok"); setConfirming(false); void timer.refetch(); },
  });
  const stop = useMutation({
    mutationFn: (minutes?: number) => unwrap(api.POST("/api/v1/timebilling/timer/stop", { body: { minutes: minutes ?? null } })),
    onSuccess: (entry) => { toast(t("timer.saved", { time: formatDuration(entry.minutes), project: entry.project_code }), "ok"); setFixing(false); void timer.refetch(); void refresh(); },
  });
  const [confirming, setConfirming] = useState(false);
  const [fixing, setFixing] = useState(false);

  if (timer.isLoading) return <Card><p className="text-sm text-muted">…</p></Card>;
  if (timer.error) return <Card><p className="text-sm text-bad">{timer.error.message} <button className="font-medium underline" onClick={() => void timer.refetch()}>{t("retry")}</button></p></Card>;

  if (!timer.data) return <StartTimer companyId={companyId} onStarted={() => void timer.refetch()} />;
  const tm = timer.data;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{tm.project_code} · {tm.project_name}{tm.task ? ` · ${tm.task}` : ""}</p>
          <p className="text-xs text-muted">{tm.running ? t("timer.running") : t("timer.paused")} · {tm.billable ? t("billable") : t("notBillable")}</p>
        </div>
        <p role="timer" aria-live="off" className={`tnum text-3xl font-semibold ${tm.running ? "text-ink" : "text-muted"}`}>{formatElapsed(seconds)}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" loading={act.isPending} onClick={() => act.mutate(tm.running ? "pause" : "resume")}>
            {tm.running ? <><Pause className="h-4 w-4" />{t("timer.pause")}</> : <><Play className="h-4 w-4" />{t("timer.resume")}</>}
          </Button>
          <Button loading={stop.isPending} onClick={() => (looksForgotten(seconds) ? setFixing(true) : stop.mutate(undefined))}><Square className="h-4 w-4" />{t("timer.stop")}</Button>
          <Button variant="ghost" aria-label={t("timer.discard")} onClick={() => setConfirming(true)}><Trash2 className="h-4 w-4" /></Button>
        </div>
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} onConfirm={() => discard.mutate()} busy={discard.isPending} danger
        title={t("timer.discard")} message={t("timer.discardAsk")} confirmLabel={t("timer.discard")} />
      <ForgottenDialog open={fixing} onClose={() => setFixing(false)} seconds={seconds} busy={stop.isPending} onSave={(minutes) => stop.mutate(minutes)} />
    </Card>
  );
}

function StartTimer({ companyId, onStarted }: { companyId: string; onStarted: () => void }) {
  const { t } = useTranslation("timebilling");
  const [project, setProject] = useState<Project | null>(null);
  const [task, setTask] = useState("");
  const [billable, setBillable] = useState(true);
  const { key, renew } = useRequestKey();
  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/timer/start", {
      params: { header: { "Idempotency-Key": key } },
      body: { project_id: project!.id, task: task.trim() || null, billable },
    })),
    onSuccess: () => { renew(); setTask(""); onStarted(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (project) start.mutate(); };
  return (
    <Card title={t("timer.title")} description={t("timer.hint")}>
      <form onSubmit={submit} className="grid items-end gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_auto_auto]">
        <Field label={t("projectField")}><ProjectPicker companyId={companyId} value={project?.id ?? ""} label={project ? `${project.code} · ${project.name}` : undefined} onChange={setProject} /></Field>
        <Field label={t("task")}><TaskInput companyId={companyId} value={task} onChange={setTask} /></Field>
        <div className="flex items-center gap-2 pb-2 text-sm"><Switch checked={billable} onChange={setBillable} label={t("billable")} />{t("billable")}</div>
        <Button type="submit" disabled={!project} loading={start.isPending}><Play className="h-4 w-4" />{t("timer.start")}</Button>
      </form>
    </Card>
  );
}

/** A timer left running for a very long time: offer to enter the minutes that were really worked. */
function ForgottenDialog({ open, onClose, seconds, busy, onSave }: { open: boolean; onClose: () => void; seconds: number; busy: boolean; onSave: (minutes: number | undefined) => void }) {
  const { t } = useTranslation("timebilling");
  const [text, setText] = useState("");
  const minutes = parseDuration(text);
  const valid = minutes !== null && minutes > 0;
  return (
    <Modal open={open} onClose={onClose} title={t("timer.longTitle")}
      footer={<>
        <Button variant="secondary" loading={busy} onClick={() => onSave(undefined)}>{t("timer.keepReal", { time: formatDuration(Math.round(seconds / 60)) })}</Button>
        <Button disabled={!valid} loading={busy} onClick={() => onSave(minutes ?? undefined)}>{t("timer.saveMine")}</Button>
      </>}>
      <p className="mb-3 text-sm text-muted">{t("timer.longHint", { time: formatDuration(Math.round(seconds / 60)) })}</p>
      <Field label={t("timer.realTime")} hint={t("timeHint")} error={text && !valid ? t("timeInvalid") : null}>
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="1:30" data-autofocus />
      </Field>
    </Modal>
  );
}

import { Play, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Button, Card, Input, unwrap, useCan, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import { clockText } from "../lib";
import type { Job } from "../types";

/** The mechanic's clock: start it when the work starts, stop it when it ends, and the time goes on the job as labour. */
export function ClockCard({ job }: { job: Job }) {
  const { t } = useTranslation("jobs");
  const canManage = useCan("jobs.manage");
  const [note, setNote] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const mine = job.timers.find((x) => x.mine);
  const others = job.timers.filter((x) => !x.mine);
  useEffect(() => {
    if (!mine) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [mine]);
  const path = { params: { path: { job_id: job.id } } };
  const start = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/timer/start", { ...path, body: { note: note.trim() || null } })), { done: t("floor.clock.started"), onDone: () => setNote("") });
  const stop = useJobAction(job.id, (discard: boolean) => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/timer/stop", { ...path, body: { discard } })), { done: t("floor.clock.stopped") });
  const usable = canManage && !job.locked;
  if (!usable && others.length === 0) return null;
  return (
    <Card title={t("floor.clock.title")}>
      {mine ? (
        <div className="space-y-3">
          <p className="tnum text-3xl font-semibold" aria-live="off">{clockText(now - new Date(mine.started_at).getTime())}</p>
          {mine.note && <p className="text-sm text-muted">{mine.note}</p>}
          <div className="flex flex-wrap gap-2">
            <Button loading={stop.isPending} onClick={() => stop.mutate(false)}><Square className="h-4 w-4" />{t("floor.clock.stop")}</Button>
            <Button variant="ghost" disabled={stop.isPending} onClick={() => stop.mutate(true)}>{t("floor.clock.discard")}</Button>
          </div>
          <p className="text-xs text-muted">{t("floor.clock.stopHint")}</p>
        </div>
      ) : usable ? (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); start.mutate(); }}>
          <Input aria-label={t("floor.clock.note")} placeholder={t("floor.clock.notePlaceholder")} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button type="submit" loading={start.isPending}><Play className="h-4 w-4" />{t("floor.clock.start")}</Button>
        </form>
      ) : null}
      {others.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-line pt-3 text-sm text-muted">
          {others.map((o) => <li key={o.id}>{t("floor.clock.other", { name: o.user_name ?? "", since: new Date(o.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) })}</li>)}
        </ul>
      )}
    </Card>
  );
}

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Card, channelOptions, Checkbox, Input, Select, Switch, unwrap, useChannels, useCompany, useDebounced, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { type NoteDraft, type NoteSchedule, noteFrom, planNoteSaves } from "../logic";

/** The daily note as one calm card: a switch, then "Send it at [time] by [way]", and an optional weekly line. Changes save by themselves. */
export default function NoteCard({ schedules, draft, onDraft }: { schedules: readonly NoteSchedule[]; draft: NoteDraft; onDraft: (d: NoteDraft) => void }) {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const { companies } = useCompany();
  const available = useChannels().data ?? [];
  const [flash, setFlash] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const manyZones = new Set(companies.map((c) => c.timezone)).size > 1;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async (list: ReturnType<typeof planNoteSaves>) => {
      for (const s of list) {
        await unwrap(api.PUT("/api/v1/command/schedules/mine/{kind}", { params: { path: { kind: s.kind } }, body: { channel: s.channel, send_time: s.send_time, weekday: s.weekday, is_active: s.is_active } }));
      }
    },
    onSuccess: () => { setProblem(null); setFlash(true); void qc.invalidateQueries({ queryKey: ["command", "schedules"] }); },
    onError: (e) => setProblem(e.message),
  });

  // Save a moment after the last change, only when the stored schedules differ.
  const settled = useDebounced(draft, 700);
  const sent = useRef("");
  useEffect(() => {
    const list = planNoteSaves(settled, schedules);
    const sig = JSON.stringify(list);
    if (list.length === 0 || sig === sent.current) return;
    sent.current = sig;
    save.mutate(list);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, schedules]);
  useEffect(() => { if (!flash) return; const id = window.setTimeout(() => setFlash(false), 2500); return () => window.clearTimeout(id); }, [flash]);

  const set = (patch: Partial<NoteDraft>) => { sent.current = ""; setFlash(false); onDraft({ ...draft, ...patch }); };
  const options = channelOptions(available, draft.channel, ["in_app"]);
  const pending = JSON.stringify(draft) !== JSON.stringify(noteFrom(schedules)) || save.isPending;

  return (
    <Card title={t("note.title")} description={t("note.hint")}
      actions={<span role="status" aria-live="polite" className="text-xs text-muted">{save.isPending ? t("note.saving") : flash ? t("note.saved") : pending ? "" : ""}</span>}>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Switch label={t("note.switch")} checked={draft.on} onChange={(on) => set({ on })} />
          <span className="text-sm font-medium">{t("note.switch")}</span>
        </div>
        {draft.on && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
              <span>{t("note.sendAt")}</span>
              <Input type="time" required className="w-36" aria-label={t("note.timeLabel")} value={draft.time} onChange={(e) => e.target.value && set({ time: e.target.value })} />
              <span>{t("note.by")}</span>
              <Select className="w-44 max-w-full" aria-label={t("note.wayLabel")} value={draft.channel} onChange={(e) => set({ channel: e.target.value })}>
                {options.map((o) => <option key={o.value} value={o.value}>{o.value === "in_app" ? t("channels.in_app") : o.missing ? t("channelGone", { channel: o.label }) : o.label}</option>)}
              </Select>
            </div>
            {manyZones && <p className="text-xs text-muted">{t("note.localTime")}</p>}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
              <Checkbox label={t("note.weeklyAlso")} checked={draft.weekly} onChange={(e) => set({ weekly: e.target.checked })} />
              {draft.weekly && (
                <Select className="w-36 max-w-full" aria-label={t("note.weekdayLabel")} value={String(draft.weekday)} onChange={(e) => set({ weekday: Number(e.target.value) })}>
                  {[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{t(`weekdays.${d}`)}</option>)}
                </Select>
              )}
            </div>
            {draft.channel !== "in_app" && <p className="text-xs text-muted">{t("profileHint")} <Link className="text-brand-strong hover:underline" to="/admin/account">{t("openProfile")}</Link></p>}
          </div>
        )}
        {problem && <Alert tone="bad">{problem}</Alert>}
      </div>
    </Card>
  );
}

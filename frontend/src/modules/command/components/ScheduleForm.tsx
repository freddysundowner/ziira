import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Card, channelOptions, Field, FormGrid, Input, Select, Switch, toast, unwrap, useChannels, useMutation, useQueryClient, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { toTimeInput } from "../logic";

type Schedule = Schemas["ScheduleOut"];
type Kind = "daily" | "weekly";

/** When and how one kind of brief reaches me. Saved as a whole; removing it stops that brief. */
export default function ScheduleForm({ kind, schedule }: { kind: Kind; schedule: Schedule | undefined }) {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const [channel, setChannel] = useState(schedule?.channel ?? "in_app");
  const available = useChannels().data ?? [];
  const [time, setTime] = useState(schedule ? toTimeInput(schedule.send_time) : "07:30");
  const [weekday, setWeekday] = useState(String(schedule?.weekday ?? 1));
  const [active, setActive] = useState(schedule?.is_active ?? true);
  const [problem, setProblem] = useState<string | null>(null);
  const done = () => void qc.invalidateQueries({ queryKey: ["command", "schedules"] });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/command/schedules/mine/{kind}", {
      params: { path: { kind } }, body: { channel, send_time: time, weekday: kind === "weekly" ? Number(weekday) : null, is_active: active } })),
    onSuccess: () => { setProblem(null); done(); toast(t("scheduleSaved"), "ok"); },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/command/schedules/mine/{kind}", { params: { path: { kind } } })),
    onSuccess: () => { done(); toast(t("scheduleRemoved"), "ok"); },
  });

  return (
    <Card title={t(`kind.${kind}`)} description={t(`kindHint.${kind}`)}
      actions={schedule && <Button size="sm" variant="ghost" loading={remove.isPending} onClick={() => remove.mutate()}>{t("stopBrief")}</Button>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <FormGrid>
          <Field label={t("channel")}>
            <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
              {channelOptions(available, channel, ["in_app"]).map((o) => <option key={o.value} value={o.value}>{o.value === "in_app" ? t("channels.in_app") : o.missing ? t("channelGone", { channel: o.label }) : o.label}</option>)}
            </Select>
          </Field>
          <Field label={t("sendTime")} hint={t("sendTimeHint")}>
            <Input type="time" required value={time} onChange={(e) => setTime(e.target.value)} />
          </Field>
          {kind === "weekly" && (
            <Field label={t("weekday")}>
              <Select value={weekday} onChange={(e) => setWeekday(e.target.value)}>
                {[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{t(`weekdays.${d}`)}</option>)}
              </Select>
            </Field>
          )}
          <div className="flex items-end gap-3 pb-2">
            <Switch label={t("active")} checked={active} onChange={setActive} />
            <span className="text-sm">{t("active")}</span>
          </div>
        </FormGrid>
        {channel !== "in_app" && <p className="text-xs text-muted">{t("profileHint")} <Link className="text-brand-strong hover:underline" to="/admin/account">{t("openProfile")}</Link></p>}
        {problem && <Alert tone="bad">{problem}</Alert>}
        <div className="flex justify-end"><Button type="submit" loading={save.isPending}>{t("save")}</Button></div>
      </form>
    </Card>
  );
}

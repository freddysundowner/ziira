import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Button, Card, channelOptions, cx, ErrorState, Field, FormGrid, Input, PageHeader, Select, SkeletonRows, Switch, toast, unwrap, useChannels, useEdition, useMutation,
  useQuery, useQueryClient, useSession, useTranslation,
} from "@/sdk";

import ThingCard from "../components/ThingCard";
import { presetFor, TOPIC_KEYS, type TopicKey } from "../plainWords";
import SampleThing from "../quick/SampleThing";
import { useGrouped } from "../useGrouped";
import { usePlain } from "../usePlain";

/** Set up Ziira in one screen: what matters, when the daily summary arrives, and a first thing to look at. Nothing is switched on until the last button. */
export default function QuickStartPage() {
  const { t } = useTranslation("intel");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const plain = usePlain();
  const { enabledUnits, can } = useSession();
  const { edition } = useEdition();
  const channels = useChannels().data ?? [];
  const topics = useQuery({ queryKey: ["intel", "topics"], queryFn: () => unwrap(api.GET("/api/v1/intel/topics")) });
  const sample = useGrouped("open", 1);
  const hasSummary = enabledUnits.has("command") && can("command.view");
  const [picked, setPicked] = useState<Set<TopicKey> | null>(null);
  const [time, setTime] = useState("07:00");
  const [channel, setChannel] = useState("email");
  const [summaryOn, setSummaryOn] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);

  const recommended = presetFor(edition?.id);
  const current: Set<TopicKey> = picked ?? new Set(topics.data?.configured ? topics.data.topics.filter((x) => x.enabled > 0).map((x) => x.key) : [...TOPIC_KEYS]);
  const toggle = (k: TopicKey) => { const next = new Set(current); if (next.has(k)) next.delete(k); else next.add(k); setPicked(next); };
  const counts = new Map((topics.data?.topics ?? []).map((x) => [x.key, x.checks]));

  const finish = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      await unwrap(api.PUT("/api/v1/intel/topics", { body: { topics: Object.fromEntries(TOPIC_KEYS.map((k) => [k, current.has(k)])) } }));
      if (hasSummary) {
        if (summaryOn) await unwrap(api.PUT("/api/v1/command/schedules/mine/{kind}", { params: { path: { kind: "daily" } }, body: { channel, send_time: time, weekday: null, is_active: true } }));
        else await api.DELETE("/api/v1/command/schedules/mine/{kind}", { params: { path: { kind: "daily" } } });
      }
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel"] }); void qc.invalidateQueries({ queryKey: ["command"] }); toast(t("quick.done"), "ok"); navigate("/intelligence"); },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });

  const error = topics.error ?? plain.error;
  return (
    <>
      <PageHeader title={t("quick.title")} description={t("quick.hint")} back={{ to: "/intelligence", label: t("today.title") }} />
      {error ? <ErrorState message={error.message} onRetry={() => void topics.refetch()} /> : !topics.data || !plain.data ? <SkeletonRows rows={6} cols={2} /> : (
        <div className="max-w-4xl space-y-4">
          <Card title={t("quick.step1")} description={t("quick.step1Hint")}
            actions={<div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => setPicked(new Set(TOPIC_KEYS))}>{t("quick.everything")}</Button>
              {recommended.length < TOPIC_KEYS.length && <Button size="sm" variant="secondary" onClick={() => setPicked(new Set(recommended))}>{t("quick.forYou", { edition: edition?.title ?? "" })}</Button>}
            </div>}>
            <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,16rem),1fr))] gap-3">
              {plain.data.topics.map((tp) => {
                const key = tp.key as TopicKey;
                const on = current.has(key);
                return (
                  <li key={key} className={cx("flex items-start justify-between gap-3 rounded-xl border p-3", on ? "border-brand bg-brand-soft" : "border-line")}>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold [overflow-wrap:anywhere]">{tp.title}</p>
                      <p className="text-xs text-muted">{tp.lead}</p>
                      <p className="mt-1 text-xs text-muted">{t("quick.watchCount", { count: counts.get(key) ?? 0 })}</p>
                    </div>
                    <Switch label={tp.title} checked={on} onChange={() => toggle(key)} />
                  </li>
                );
              })}
            </ul>
            {current.size === 0 && <Alert tone="warn" className="mt-3">{t("quick.noneChosen")}</Alert>}
          </Card>
          {hasSummary && (
            <Card title={t("quick.step2")} description={t("quick.step2Hint")}>
              <div className="space-y-3">
                <div className="flex items-center gap-2"><Switch label={t("quick.summaryOn")} checked={summaryOn} onChange={setSummaryOn} /><span className="text-sm">{t("quick.summaryOn")}</span></div>
                {summaryOn && (
                  <FormGrid>
                    <Field label={t("quick.time")} hint={t("quick.timeHint")}><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
                    <Field label={t("quick.where")}>
                      <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
                        {channelOptions(channels, channel, ["in_app"]).map((o) => <option key={o.value} value={o.value}>{o.value === "in_app" ? t("summary.inAppOption") : o.label}</option>)}
                      </Select>
                    </Field>
                  </FormGrid>
                )}
              </div>
            </Card>
          )}
          <Card title={t("quick.step3")} description={t("quick.step3Hint")}>
            {sample.data && sample.data.groups.length > 0 ? <ThingCard group={sample.data.groups[0]} actions={false} /> : <SampleThing />}
          </Card>
          {problem && <Alert tone="bad">{problem}</Alert>}
          <div className="flex justify-end"><Button size="lg" loading={finish.isPending} disabled={current.size === 0} onClick={() => finish.mutate()}>{t("quick.finish")}</Button></div>
        </div>
      )}
    </>
  );
}

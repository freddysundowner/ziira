import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Card, ConfirmDialog, ErrorState, PageHeader, SkeletonRows, Switch, toast, unwrap, useCompany, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import Glossary from "../components/Glossary";
import RunChecks from "../components/RunChecks";
import { atDefaults, type Check } from "../logic";
import { TOPIC_KEYS } from "../plainWords";
import { useTechnical } from "../useTechnical";
import { usePlain } from "../usePlain";
import IgnoreRules from "../watching/IgnoreRules";
import WatchRow from "../watching/WatchRow";

/** What Ziira watches: every check in plain words, grouped by what matters (cash, stock, customers, ...), each tunable and switchable. */
export default function WatchingPage() {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const plain = usePlain();
  const { company } = useCompany();
  const [technical, setTechnical] = useTechnical();
  const [resetting, setResetting] = useState(false);
  const checks = useQuery({ queryKey: ["intel", "checks"], queryFn: () => unwrap(api.GET("/api/v1/intel/checks")) });
  const topics = useQuery({ queryKey: ["intel", "topics"], queryFn: () => unwrap(api.GET("/api/v1/intel/topics")) });

  const setTopic = useMutation({
    mutationFn: (v: { key: string; on: boolean }) => unwrap(api.PUT("/api/v1/intel/topics", { body: { topics: { [v.key]: v.on } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel"] }); toast(t("watch.topicSaved"), "ok"); },
  });
  const resetAll = useMutation({
    mutationFn: async () => {
      for (const c of (checks.data ?? []).filter((x) => !x.enabled || !atDefaults(x))) await unwrap(api.POST("/api/v1/intel/checks/{code}/reset", { params: { path: { code: c.code } } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel"] }); setResetting(false); toast(t("watch.resetAllDone"), "ok"); },
    onError: () => setResetting(false),
  });

  const error = checks.error ?? topics.error ?? plain.error;
  const byTopic = (key: string): Check[] => (checks.data ?? []).filter((c) => c.topic === key)
    .sort((a, b) => (plain.check(a.code)?.title ?? a.title).localeCompare(plain.check(b.code)?.title ?? b.title));

  return (
    <>
      <PageHeader title={t("watch.title")} description={t("watch.hint")}
        actions={<><Link to="/intelligence/setup" className="text-sm font-medium text-brand-strong hover:underline">{t("watch.setupAgain")}</Link><Glossary terms={["yourNormal", "watches"]} /></>} />
      <div className="space-y-4">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 text-sm"><Switch label={t("tech.names")} checked={technical} onChange={setTechnical} />{t("tech.names")}</span>
            <button type="button" className="text-sm font-medium text-brand-strong hover:underline" onClick={() => setResetting(true)}>{t("watch.resetAll")}</button>
          </div>
        </Card>
        <RunChecks />
        {error ? <ErrorState message={error.message} onRetry={() => { void checks.refetch(); void topics.refetch(); }} />
          : !checks.data || !plain.data ? <SkeletonRows rows={6} cols={2} />
            : TOPIC_KEYS.map((key) => {
              const list = byTopic(key);
              if (list.length === 0) return null;
              const on = list.filter((c) => c.enabled).length;
              const topic = plain.data!.topics.find((x) => x.key === key);
              return (
                <Card key={key} title={topic?.title ?? key} description={`${topic?.lead ?? ""} ${t("watch.countOn", { on, total: list.length })}`.trim()}
                  actions={<Switch label={t("watch.topicSwitch", { topic: topic?.title ?? key })} checked={on > 0} disabled={setTopic.isPending} onChange={(v) => setTopic.mutate({ key, on: v })} />}>
                  <div className="divide-y divide-line">
                    {list.map((c) => <WatchRow key={`${c.code}-${JSON.stringify(c.params)}-${c.enabled}`} check={c} text={plain.check(c.code)} labels={plain.data!.params} technical={technical} companyId={company?.id} />)}
                  </div>
                </Card>
              );
            })}
        <IgnoreRules />
      </div>
      <ConfirmDialog open={resetting} onClose={() => setResetting(false)} busy={resetAll.isPending} title={t("watch.resetAllTitle")} message={t("watch.resetAllAsk")}
        confirmLabel={t("watch.resetAll")} onConfirm={() => resetAll.mutate()} />
    </>
  );
}

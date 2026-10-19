import { Check, Circle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Button, Card, ConfirmDialog, toast, unwrap, useCan, useMutation, useQuery, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import type { Setup } from "../types";

const WHERE: Record<string, string> = { service_item: "/time/settings", rates: "/time/rates", team: "/time/rates", client_project: "/projects", time: "/time", invoice: "/time/unbilled" };

/** The first-run checklist: six steps that tick themselves from what the business has done, and the pack's sample practice. */
export function GetStarted({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const canManage = useCan("projects.manage");
  const [removing, setRemoving] = useState(false);
  const setup = useQuery<Setup>({
    queryKey: ["timebilling", "setup", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/setup", { params: { query: { company_id: companyId } } })),
  });
  const load = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/sample-data", { params: { query: { company_id: companyId } } })),
    onSuccess: () => { toast(t("start.sampleAdded"), "ok"); void refresh(); },
  });
  const drop = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/timebilling/sample-data", { params: { query: { company_id: companyId } } })),
    onSuccess: () => { setRemoving(false); toast(t("start.sampleRemoved"), "ok"); void refresh(); },
  });
  const data = setup.data;
  if (!data) return null;
  const left = data.steps.filter((s) => !s.done).length;
  if (left === 0 && !data.sample.loaded) return null;
  return (
    <Card title={t("start.title")} description={left ? t("start.left", { count: left }) : t("start.allDone")} className="mb-4">
      <ol className="space-y-2 text-sm">
        {data.steps.map((s) => (
          <li key={s.key} className="flex items-start gap-2">
            {s.done ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />}
            <span className="min-w-0"><Link className={s.done ? "text-muted line-through" : "font-medium hover:underline"} to={WHERE[s.key] ?? "/time"}>{t(`start.step.${s.key}`)}</Link>{!s.done && <span className="block text-xs text-muted">{t(`start.hint.${s.key}`)}</span>}</span>
          </li>
        ))}
      </ol>
      {data.example_rates > 0 && <p className="mt-3 text-xs text-warn">{t("start.exampleRates", { count: data.example_rates })}</p>}
      {canManage && data.sample.available && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
          {data.sample.loaded
            ? <><p className="text-sm text-muted">{t("start.sampleLoaded")}</p><Button size="sm" variant="secondary" onClick={() => setRemoving(true)}>{t("start.removeSample")}</Button></>
            : <><p className="text-sm text-muted">{data.sample.note ?? t("start.sampleHint")}</p><Button size="sm" variant="secondary" loading={load.isPending} onClick={() => load.mutate()}>{t("start.addSample")}</Button></>}
        </div>
      )}
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} onConfirm={() => drop.mutate()} busy={drop.isPending} danger title={t("start.removeSample")} message={t("start.removeAsk")} confirmLabel={t("start.removeSample")} />
    </Card>
  );
}

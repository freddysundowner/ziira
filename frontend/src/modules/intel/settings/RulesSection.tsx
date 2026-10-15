import { useState } from "react";

import {
  Alert, api, Badge, type BadgeTone, Button, Card, ConfirmDialog, EmptyState, ErrorState, SkeletonRows, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { type ActionType, type Rule, ruleState, type RuleState } from "../actions/logic";
import { describeConditions, fieldsOf } from "../actions/schema";
import RuleDrawer from "./RuleDrawer";
import { useWording } from "./useWording";

const TONE: Record<RuleState, BadgeTone> = { active: "ok", paused: "warn", off: "neutral" };

/** The rules that let Intelligence do routine, no-money actions by itself. They do nothing below level 4. */
export default function RulesSection({ companyId, level }: { companyId: string; level: number }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const words = useWording(companyId);
  const isOwner = useCan("intel.automation");           // making, widening or switching on a rule is the owner's decision
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [switchingOff, setSwitchingOff] = useState<Rule | null>(null);
  const types = useQuery({ queryKey: ["intel", "action-types"], queryFn: () => unwrap(api.GET("/api/v1/intel/actions/types")), staleTime: 300_000 });
  const rules = useQuery({ queryKey: ["intel", "rules"], queryFn: () => unwrap(api.GET("/api/v1/intel/automation/rules")) });

  const update = useMutation({
    mutationFn: (v: { id: string; body: { enabled?: boolean; paused?: boolean } }) =>
      unwrap(api.PATCH("/api/v1/intel/automation/rules/{rule_id}", { params: { path: { rule_id: v.id } }, body: v.body })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel", "rules"] }); toast(t("rules.saved"), "ok"); },
  });

  if (types.error || rules.error) {
    return <Card title={t("rules.title")}><ErrorState message={(types.error ?? rules.error)!.message} onRetry={() => { void types.refetch(); void rules.refetch(); }} /></Card>;
  }
  if (!types.data || !rules.data) return <SkeletonRows rows={3} cols={2} />;
  const mine = rules.data.filter((r) => r.company_id === companyId);
  const automatic = types.data.filter((a) => a.can_run_by_rule);
  const never = types.data.filter((a) => !a.can_run_by_rule);
  const typeOf = (r: Rule): ActionType | undefined => types.data.find((a) => a.type === r.action_type);

  return (
    <Card title={t("rules.title")} description={t("rules.hint")}
      actions={isOwner ? <Button size="sm" disabled={automatic.length === 0} onClick={() => setEditing("new")}>{t("rules.add")}</Button> : undefined}>
      <div className="space-y-4">
        {!isOwner && <Alert tone="info">{t("rules.ownerOnly")}</Alert>}
        {level < 4 && <Alert tone="warn">{t("rules.belowLevel")}</Alert>}
        {mine.length === 0 ? (
          <EmptyState title={t("rules.none")} hint={t("rules.noneHint")} />
        ) : (
          <ul className="divide-y divide-line">
            {mine.map((r) => {
              const state = ruleState(r);
              const sentences = describeConditions(fieldsOf(typeOf(r)?.rule_schema), r.conditions, words);
              return (
                <li key={r.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold">{r.action_title}</h3>
                    <Badge tone={TONE[state]}>{t(`rules.state.${state}`)}</Badge>
                  </div>
                  <p className="text-sm">{sentences.length > 0 ? sentences.join(" · ") : t("rules.anyCase")}</p>
                  <p className="text-xs text-muted">{t("rules.limitUsed", { cap: r.daily_cap, count: r.times_used })}{r.note ? ` · ${r.note}` : ""}</p>
                  <div className="flex flex-wrap gap-2">
                    {r.enabled && (isOwner || !r.paused) && <Button size="sm" variant="secondary" loading={update.isPending && update.variables?.id === r.id} onClick={() => update.mutate({ id: r.id, body: { paused: !r.paused } })}>{r.paused ? t("rules.resume") : t("rules.pause")}</Button>}
                    {isOwner && <Button size="sm" variant="secondary" onClick={() => setEditing(r)}>{t("rules.edit")}</Button>}
                    {r.enabled
                      ? <Button size="sm" variant="ghost" onClick={() => setSwitchingOff(r)}>{t("rules.switchOff")}</Button>
                      : isOwner && <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: r.id, body: { enabled: true } })}>{t("rules.switchOn")}</Button>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {never.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer font-medium">{t("rules.neverAutomatic")}</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">{never.map((a) => <li key={a.type}><span className="text-ink">{a.title}</span>{a.why_not_by_rule ? `: ${a.why_not_by_rule}` : ""}</li>)}</ul>
          </details>
        )}
      </div>
      {editing && <RuleDrawer companyId={companyId} rule={editing === "new" ? null : editing} types={automatic} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!switchingOff} onClose={() => setSwitchingOff(null)} busy={update.isPending} danger title={t("rules.switchOffTitle")} confirmLabel={t("rules.switchOff")}
        message={t("rules.switchOffAsk", { action: switchingOff?.action_title })}
        onConfirm={() => { if (switchingOff) update.mutate({ id: switchingOff.id, body: { enabled: false } }, { onSettled: () => setSwitchingOff(null) }); }} />
    </Card>
  );
}

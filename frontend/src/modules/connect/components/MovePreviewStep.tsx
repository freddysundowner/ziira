import { Alert, Badge, Button, Card, DataTable, Stat, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { totals } from "../moveLogic";

type Plan = Schemas["PlanOut"];
type KindPlan = Schemas["KindPlanOut"];

/** One kind: what will be created, what is already in Ziira, what cannot be brought, and why. */
function KindCard({ k }: { k: KindPlan }) {
  const { t } = useTranslation("connect");
  const columns = Object.keys(k.sample[0] ?? {}).filter((c) => k.sample.some((r) => r[c]));
  return (
    <Card title={t(`move.kind.${k.kind}`)} description={t("move.preview.counts", { found: k.candidates, create: k.create, exists: k.exists, skipped: k.skipped })}>
      <div className="space-y-3">
        {k.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
        {k.reasons.length > 0 && (
          <ul className="space-y-1.5 text-sm">
            {k.reasons.map((r) => (
              <li key={`${r.status}:${r.reason}`} className="flex flex-wrap items-start gap-2">
                <Badge tone={r.status === "exists" ? "info" : "warn"}>{t(`move.preview.${r.status}Badge`)}</Badge>
                <span className="tnum font-medium">{r.count}</span>
                <span className="min-w-0 flex-1">{r.reason}{r.examples.length > 0 && <span className="block text-xs text-muted">{t("move.preview.examples", { names: r.examples.join(", ") })}</span>}</span>
              </li>
            ))}
          </ul>
        )}
        {k.sample.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("move.preview.sample", { count: k.sample.length })}</p>
            <DataTable rows={k.sample} empty={{ title: t("move.preview.nothingHere") }} rowKey={(r) => Object.values(r).join("|")} columns={columns.map((c, i) => ({ header: t(`move.field.${c}`, { defaultValue: c }), hideBelow: i > 2 ? "md" : undefined, cell: (r: Record<string, string>) => r[c] || "—" }))} />
          </div>
        )}
        {k.create === 0 && k.reasons.length === 0 && <p className="text-sm text-muted">{t("move.preview.nothingHere")}</p>}
      </div>
    </Card>
  );
}

/** Step two: exactly what bringing the data over would do. Nothing has been written yet. */
export function MovePreviewStep({ plan, busy, error, onBack, onConfirm }: { plan: Plan; busy: boolean; error?: string; onBack: () => void; onConfirm: () => void }) {
  const { t } = useTranslation("connect");
  const sum = totals(plan.kinds);
  const chosen = plan.kinds.filter((k) => k.selected);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label={t("move.preview.create")} value={sum.create} tone={sum.create > 0 ? "ok" : undefined} />
        <Stat label={t("move.preview.exists")} value={sum.exists} />
        <Stat label={t("move.preview.skipped")} value={sum.skipped} />
      </div>
      <Alert tone="info">{t("move.preview.notYet", { date: plan.as_of })}</Alert>
      {chosen.map((k) => <KindCard key={k.kind} k={k} />)}
      {plan.users > 0 && <Alert tone="info">{t("move.preview.users", { count: plan.users })}</Alert>}
      {error && <Alert tone="bad">{error}</Alert>}
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="secondary" onClick={onBack}>{t("back")}</Button>
        <Button loading={busy} disabled={sum.create === 0} onClick={onConfirm}>{sum.create === 0 ? t("move.preview.nothingNew") : t("move.preview.confirm", { count: sum.create })}</Button>
      </div>
    </div>
  );
}

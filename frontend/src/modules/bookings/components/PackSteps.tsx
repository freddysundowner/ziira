import { Check, Circle } from "lucide-react";
import { Link } from "react-router-dom";

import { api, Button, Card, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

/** The first-run checklist an industry pack gave the business. Shows nothing when there are no steps or they are hidden. */
export function PackSteps({ companyId }: { companyId: string }) {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const qc = useQueryClient();
  const steps = useQuery({
    queryKey: ["bookings", "pack-steps", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/pack-steps", { params: { query: { company_id: companyId } } })),
  });
  const hide = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/bookings/pack-steps/visibility", { body: { company_id: companyId, hidden: true } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bookings", "pack-steps", companyId] }),
  });
  const list = (steps.data ?? []).filter((s) => !s.hidden);
  if (list.length === 0) return null;
  const done = list.filter((s) => s.done).length;
  return (
    <Card title={t("packSteps.title")} description={t("packSteps.progress", { done, total: list.length })}
      actions={canSetup ? <Button size="sm" variant="ghost" loading={hide.isPending} onClick={() => hide.mutate()}>{t("packSteps.hide")}</Button> : undefined}>
      <ul className="divide-y divide-line">
        {list.map((s) => (
          <li key={s.id} className="flex items-start gap-3 py-2.5">
            <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${s.done ? "bg-ok text-ok-ink" : "border border-line text-muted"}`} aria-hidden>
              {s.done ? <Check className="h-3 w-3" /> : <Circle className="h-2 w-2" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className={`text-sm font-medium ${s.done ? "text-muted line-through" : ""}`}>
                <span className="sr-only">{s.done ? t("packSteps.done") : t("packSteps.todo")}: </span>{s.title}
              </p>
              {s.hint && <p className="text-xs text-muted">{s.hint}</p>}
            </div>
            {s.to_path && !s.done && <Link to={s.to_path} className="shrink-0 rounded-lg px-2 py-1.5 text-sm font-semibold text-brand-strong hover:bg-brand-soft">{t("packSteps.open")}</Link>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

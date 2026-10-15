import { Check, Lock } from "lucide-react";
import { Link } from "react-router-dom";

import { api, Button, ErrorState, Skeleton, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { coveragePercent, sortEntities } from "../logic";

/** What Intelligence can and cannot check with what is connected today, by area, and what to connect to check more. */
export function CoveragePanel({ companyId, compact }: { companyId: string; compact?: boolean }) {
  const { t } = useTranslation("connect");
  const canManage = useCan("connect.manage");
  const coverage = useQuery({ queryKey: ["connect", "coverage", companyId], queryFn: () => unwrap(api.GET("/api/v1/connect/coverage", { params: { query: { company_id: companyId } } })) });
  const kinds = useQuery({ queryKey: ["connect", "kinds"], queryFn: () => unwrap(api.GET("/api/v1/connect/kinds")) });
  if (coverage.isLoading) return <Skeleton className="h-32 w-full" />;
  if (coverage.error || !coverage.data) return <ErrorState message={coverage.error?.message} onRetry={() => void coverage.refetch()} />;
  const data = coverage.data;
  const titles = Object.fromEntries((kinds.data ?? []).map((k) => [k.kind, k.title]));
  const percent = coveragePercent(data.areas);
  const missing = data.areas.some((a) => a.active < a.total);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="tnum text-2xl font-semibold">{percent}%</span>
        <span className="text-muted">{t("coverage.summary")}</span>
        {Object.keys(data.connected).length === 0 && <span className="text-muted">{t("coverage.nothing")}</span>}
      </div>
      {Object.keys(data.connected).length > 0 && (
        <p className="text-xs text-muted">{t("coverage.reads")}: {sortEntities(Object.keys(data.connected)).map((e) => t(`entity.${e}`, { defaultValue: e })).join(", ")}</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {data.areas.map((area) => (
          <section key={area.area} className="rounded-lg border border-line p-3">
            <h3 className="flex items-center justify-between text-sm font-medium">
              {t(`area.${area.area}`, { defaultValue: area.area })}
              <span className="tnum text-xs text-muted">{area.active}/{area.total}</span>
            </h3>
            {!compact && (
              <ul className="mt-2 space-y-1.5">
                {area.checks.map((c) => (
                  <li key={c.code} className="flex items-start gap-2 text-xs">
                    {c.active ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" aria-label={t("coverage.on")} /> : <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" aria-label={t("coverage.off")} />}
                    <span className={c.active ? "" : "text-muted"}>
                      {c.title}
                      {!c.active && c.connect.length > 0 && <span className="block">{t("coverage.connectHint", { what: c.connect.map((k) => titles[k] ?? k).slice(0, 3).join(", ") })}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
      {missing && canManage && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-soft px-3 py-2 text-sm text-brand-strong">
          <span>{t("coverage.nudge")}</span>
          <Link to="/connect/new"><Button size="sm">{t("add")}</Button></Link>
        </div>
      )}
    </div>
  );
}

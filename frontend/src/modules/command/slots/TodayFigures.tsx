import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, EmptyState, ErrorState, formatDate, humanise, SkeletonRows, toast, unwrap, useCan, useCompany, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import FigureCard from "../components/FigureCard";
import { byArea, type Figure, groupFigures } from "../logic";

/** "How the business is doing": today's figures against yesterday, company-wide and per branch, at the bottom of Intelligence's Today page. */
export default function TodayFigures() {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const canRefresh = useCan("briefs.manage");
  const [open, setOpen] = useState(false);
  const { company } = useCompany();
  const key = ["command", "overview", company?.id];
  const overview = useQuery({
    enabled: open && !!company?.id, queryKey: key, refetchInterval: 120_000,
    queryFn: () => unwrap(api.GET("/api/v1/command/overview", { params: { query: { company_id: company?.id } } })),
  });
  const refresh = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/command/pulse/refresh", { params: { query: { company_id: company?.id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast(t("refreshed"), "ok"); },
  });
  const data = overview.data;
  const groups = groupFigures(data?.figures ?? []);
  const when = data?.refreshed_at ? t("lastRefreshed", { time: formatDate(data.refreshed_at, true) }) : t("neverRefreshed");

  if (!open) return <Button variant="secondary" onClick={() => setOpen(true)}>{t("figuresShow")}</Button>;
  return (
    <Card title={t("figuresTitle")} description={data ? t("figuresHint", { date: formatDate(data.day) }) : undefined}
      actions={canRefresh && <Button size="sm" variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw className="h-3.5 w-3.5" />{t("refresh")}</Button>}>
      {overview.error ? <ErrorState message={overview.error.message} onRetry={() => void overview.refetch()} />
        : !data ? <SkeletonRows rows={3} cols={3} />
          : data.figures.length === 0 ? <EmptyState title={t("emptyTitle")} hint={t("emptyHint")} />
            : (
              <div className="space-y-6">
                <p className="text-xs text-muted">{when}</p>
                {groups.company.length > 0 && <section aria-label={t("companyWide")}><h3 className="mb-2 text-sm font-semibold">{t("companyWide")}</h3><FigureAreas figures={groups.company} currency={data.currency} /></section>}
                {groups.branches.map((b) => (
                  <section key={b.id} aria-label={b.name}><h3 className="mb-2 text-sm font-semibold">{t("branchHeading", { name: b.name })}</h3><FigureAreas figures={b.figures} currency={data.currency} /></section>
                ))}
              </div>
            )}
    </Card>
  );
}

/** Figures laid out by area, each with its own small heading. */
function FigureAreas({ figures, currency }: { figures: Figure[]; currency: string }) {
  const { t } = useTranslation("command");
  return (
    <div className="space-y-4">
      {byArea(figures).map((g) => (
        <div key={g.area}>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{t(`area.${g.area}`, { defaultValue: humanise(g.area) })}</h4>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.figures.map((f) => <FigureCard key={`${f.metric}-${f.branch_id ?? ""}`} figure={f} currency={currency} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

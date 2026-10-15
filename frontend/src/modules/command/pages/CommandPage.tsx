import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Button, Card, EmptyState, ErrorState, formatDate, humanise, PageHeader, Select, SkeletonRows, Slot, toast, unwrap, useCan, useCompany, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import AttentionPanel from "../components/AttentionPanel";
import FigureCard from "../components/FigureCard";
import { byArea, type Figure, groupFigures } from "../logic";
import { COMMAND_PANELS } from "../public";

export default function CommandPage() {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const canRefresh = useCan("briefs.manage");
  const { company, companies } = useCompany();
  const [picked, setPicked] = useState("");
  const companyId = picked || company?.id;
  const key = ["command", "overview", companyId];
  const overview = useQuery({
    enabled: !!companyId, queryKey: key, refetchInterval: 120_000,
    queryFn: () => unwrap(api.GET("/api/v1/command/overview", { params: { query: { company_id: companyId } } })),
  });
  const refresh = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/command/pulse/refresh", { params: { query: { company_id: companyId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast(t("refreshed"), "ok"); },
  });

  const data = overview.data;
  const groups = groupFigures(data?.figures ?? []);
  const when = data?.refreshed_at ? t("lastRefreshed", { time: formatDate(data.refreshed_at, true) }) : t("neverRefreshed");

  return (
    <>
      <PageHeader title={t("title")} description={data ? t("hint", { company: data.company_name, date: formatDate(data.day) }) : t("hintShort")}
        actions={
          <>
            {companies.length > 1 && (
              <Select aria-label={t("company")} value={companyId ?? ""} onChange={(e) => setPicked(e.target.value)}>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            )}
            <Link to="/command/briefs" className="text-sm font-medium text-brand-strong hover:underline">{t("myBriefs")}</Link>
          </>
        } />
      {overview.error ? <ErrorState message={overview.error.message} onRetry={() => void overview.refetch()} />
        : !data ? <SkeletonRows rows={6} cols={3} /> : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <span>{when}</span>
              {canRefresh && <Button size="sm" variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw className="h-3.5 w-3.5" />{t("refresh")}</Button>}
            </div>
            <AttentionPanel overview={data} />
            <Slot name={COMMAND_PANELS} props={{ companyId }} />
            {data.figures.length === 0 ? (
              <Card><EmptyState title={t("emptyTitle")} hint={t("emptyHint")}
                action={canRefresh ? <Button variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate()}>{t("refresh")}</Button> : undefined} /></Card>
            ) : (
              <>
                {groups.company.length > 0 && (
                  <section aria-label={t("companyWide")}>
                    <h2 className="mb-2 text-sm font-semibold">{t("companyWide")}</h2>
                    <FigureAreas figures={groups.company} currency={data.currency} />
                  </section>
                )}
                {groups.branches.map((b) => (
                  <section key={b.id} aria-label={b.name}>
                    <h2 className="mb-2 text-sm font-semibold">{t("branchHeading", { name: b.name })}</h2>
                    <FigureAreas figures={b.figures} currency={data.currency} />
                  </section>
                ))}
              </>
            )}
          </div>
        )}
    </>
  );
}

/** Figures laid out by area, each with its own small heading. */
function FigureAreas({ figures, currency }: { figures: Figure[]; currency: string }) {
  const { t } = useTranslation("command");
  return (
    <div className="space-y-4">
      {byArea(figures).map((g) => (
        <div key={g.area}>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{t(`area.${g.area}`, { defaultValue: humanise(g.area) })}</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.figures.map((f) => <FigureCard key={`${f.metric}-${f.branch_id ?? ""}`} figure={f} currency={currency} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

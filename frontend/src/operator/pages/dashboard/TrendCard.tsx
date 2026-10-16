import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { cx, ErrorState, formatDate, money, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { ColumnChart, LineChart } from "../../components/charts";
import { Card } from "@/sdk";

const METRICS = ["revenue", "signups", "churn"] as const;
const RANGES = ["12m", "12w"] as const;
type Metric = (typeof METRICS)[number];
type Range = (typeof RANGES)[number];

function Chips<T extends string>({ label, options, value, onChange, text }: { label: string; options: readonly T[]; value: T; onChange: (v: T) => void; text: (o: T) => string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-line p-0.5">
      {options.map((o) => (
        <button key={o} type="button" aria-pressed={value === o} onClick={() => onChange(o)}
          className={cx("rounded-md px-2.5 py-1 text-xs font-medium focus-visible:ring-2 focus-visible:ring-brand", value === o ? "bg-brand-soft text-brand-strong" : "text-muted hover:text-ink")}>{text(o)}</button>
      ))}
    </div>
  );
}

/** Money collected (a chart per currency), new businesses or businesses lost, over the last 12 months or 12 weeks. */
export function TrendCard() {
  const { t } = useTranslation("operator");
  const [metric, setMetric] = useState<Metric>("revenue");
  const [range, setRange] = useState<Range>("12m");
  const [currency, setCurrency] = useState<string | null>(null);
  const series = useQuery({
    queryKey: ["operator", "series", metric, range],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/dashboard/series", { params: { query: { metric, range } } })),
  });
  const labels = (series.data?.buckets ?? []).map((b) => formatDate(b).replace(/^\d{1,2}\s/, ""));
  const lines = series.data?.series ?? [];
  const line = lines.find((l) => l.currency === currency) ?? lines[0];
  return (
    <Card title={t("dash.trend.title")} description={t(`dash.trend.hint.${metric}`)}
      actions={<><Chips label={t("dash.trend.metric")} options={METRICS} value={metric} onChange={(m) => { setMetric(m); setCurrency(null); }} text={(m) => t(`dash.trend.metrics.${m}`)} />
        <Chips label={t("dash.trend.range")} options={RANGES} value={range} onChange={setRange} text={(r) => t(`dash.trend.ranges.${r}`)} /></>}>
      {series.isPending ? <Skeleton className="h-56 w-full" /> : series.isError ? <ErrorState title={t("dash.trend.failed")} message={series.error.message} onRetry={() => void series.refetch()} /> : (
        <>
          {metric === "revenue" && lines.length > 1 && (
            <div className="mb-2"><Chips label={t("dash.trend.currency")} options={lines.map((l) => l.currency ?? "")} value={line?.currency ?? ""} onChange={setCurrency} text={(c) => c} /></div>
          )}
          {metric === "revenue" ? (
            <LineChart labels={labels} values={(line?.points ?? []).map(Number)} label={t("dash.trend.aria", { metric: t("dash.trend.metrics.revenue"), currency: line?.currency ?? "" })}
              format={(v) => money(String(v), line?.currency ?? "")} empty={t("dash.trend.emptyRevenue")} />
          ) : (
            <ColumnChart labels={labels} values={(line?.points ?? []).map(Number)} label={t("dash.trend.aria", { metric: t(`dash.trend.metrics.${metric}`), currency: "" })}
              format={(v) => String(v)} empty={t("dash.trend.emptyCount")} />
          )}
          <p className="mt-2 text-xs text-muted">{t("dash.trend.note")}</p>
        </>
      )}
    </Card>
  );
}

import { Card, type Schemas, useTranslation } from "@/sdk";

import { BarList } from "../../components/bits";
import { Donut } from "../../components/charts";

/** Where the businesses are: by state (a ring), plan, edition and country (bars; each row opens the filtered list). */
export function Breakdowns({ d }: { d: Schemas["DashboardOut"] }) {
  const { t } = useTranslation("operator");
  const bars = (counts: Record<string, number>, param: string, label: (key: string) => string) =>
    Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ key, label: label(key), value, to: `/operator/subscribers?${param}=${encodeURIComponent(key)}` }));
  const states = Object.entries(d.by_status).sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ key, label: t(`status.${key}`, key), value }));
  const total = states.reduce((n, s) => n + s.value, 0);
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card title={t("dash.byStatus")}><Donut parts={states} label={t("dash.byStatus")} empty={t("dash.noData")} centre={total ? String(total) : undefined} /></Card>
      <Card title={t("dash.byPlan")}><BarList empty={t("dash.noData")} items={bars(d.by_plan, "plan", (k) => k)} /></Card>
      <Card title={t("dash.byEdition")}><BarList empty={t("dash.noData")} items={bars(d.by_edition, "edition", (k) => k)} /></Card>
      <Card title={t("dash.byCountry")}><BarList empty={t("dash.noData")} items={bars(d.by_country, "country", (k) => k)} /></Card>
    </div>
  );
}

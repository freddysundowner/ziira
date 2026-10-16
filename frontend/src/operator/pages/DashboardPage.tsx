import { RefreshCw } from "lucide-react";

import { Badge, Button, ErrorState, formatDate, humanise, PageHeader, Skeleton, useTranslation } from "@/sdk";

import { SetupChecklist } from "../components/SetupChecklist";
import { Breakdowns } from "./dashboard/Breakdowns";
import { Feeds } from "./dashboard/Feeds";
import { Kpis } from "./dashboard/Kpis";
import { QuickActions } from "./dashboard/QuickActions";
import { useDashboardQueries } from "./dashboard/queries";
import { SystemTiles } from "./dashboard/SystemTiles";
import { Tables } from "./dashboard/Tables";
import { TrendCard } from "./dashboard/TrendCard";

/**
 * The landing page: set-up checklist (until finished), headline figures, trend, platform health, breakdowns, who renews or
 * is about to lose a trial, the newest payments and sign-ups and recent operator activity, with quick actions on top.
 * Every block reads its own data, so one failing read never blanks the page.
 */
export default function DashboardPage() {
  const { t } = useTranslation("operator");
  const { overview } = useDashboardQueries();
  const refresh = (
    <Button variant="secondary" size="sm" loading={overview.isFetching && !overview.isPending} onClick={() => void overview.refetch()}>
      <RefreshCw className="h-4 w-4" /> {t("dash.refresh")}
    </Button>
  );
  const d = overview.data;
  return (
    <div className="space-y-5">
      <PageHeader title={t("dash.title")}
        description={d ? t("dash.description", { days: d.period_days, time: formatDate(d.generated_at, true) }) : t("dash.welcome")}
        actions={<>{d && <Badge tone="brand" className="py-1">{t("dash.mode", { mode: t(`dash.modes.${d.mode}`, humanise(d.mode)) })}</Badge>}{refresh}</>} />
      <QuickActions />
      <SetupChecklist />
      {overview.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      ) : overview.isError ? (
        <ErrorState title={t("dash.loadFailed")} message={overview.error.message} onRetry={() => void overview.refetch()} />
      ) : <Kpis d={overview.data} />}
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="min-w-0 xl:col-span-2 [&>section]:h-full"><TrendCard /></div>
        <div className="min-w-0 [&>section]:h-full"><SystemTiles /></div>
      </div>
      {d && (
        <>
          <Breakdowns d={d} />
          <Tables d={d} />
        </>
      )}
      <Feeds />
    </div>
  );
}

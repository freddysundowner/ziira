import { Link } from "react-router-dom";

import { api, Card, EmptyState, ErrorState, formatDate, PageHeader, SkeletonRows, Slot, today as todayDate, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";

import { COMMAND_PANELS } from "@/modules/command/public";

import AskBox from "../components/AskBox";
import ThingCard from "../components/ThingCard";
import { daySummary } from "../plainWords";
import { TODAY_PANELS } from "../public";
import SeeStrip from "../today/SeeStrip";
import SummaryStrip from "../today/SummaryStrip";
import { useGrouped } from "../useGrouped";

const SHOWN = 5;

/** The landing page of Intelligence: what needs the person today, in a sentence, the five most pressing things, and a box to ask. */
export default function TodayPage() {
  const { t } = useTranslation("intel");
  const canManage = useCan("findings.manage");
  const canAsk = useCan("ai.ask");
  const { company } = useCompany();
  const list = useGrouped("open", SHOWN);
  const topics = useQuery({ queryKey: ["intel", "topics"], queryFn: () => unwrap(api.GET("/api/v1/intel/topics")) });
  const data = list.data;
  const sum = data ? daySummary(data.total_groups, data.urgent_groups) : null;

  return (
    <>
      <PageHeader title={t("today.title")} description={formatDate(todayDate())} />
      {canManage && topics.data && !topics.data.configured && (
        <Card className="mb-4" title={t("today.setupTitle")} description={t("today.setupHint")}
          actions={<Link to="/intelligence/setup" className="btn-gradient inline-flex h-9 items-center rounded-lg px-3.5 text-sm font-medium ">{t("today.setupAction")}</Link>}>
          <></>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-live="polite" className="min-w-0 space-y-4">
          {list.error ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
            : !data || !sum ? <SkeletonRows rows={4} cols={2} /> : (
              <>
                <div>
                  <h2 className="text-xl font-semibold sm:text-2xl">
                    {sum.tone === "none" ? t("today.nothing") : t("today.need", { count: sum.need })}
                    {sum.tone === "some" && <> {t("today.urgent", { count: sum.urgent })}</>}
                    {sum.tone === "all" && <> {t(sum.need === 1 ? "today.itIsUrgent" : "today.allUrgent")}</>}
                  </h2>
                  {sum.tone === "none" && <p className="mt-1 text-sm text-muted">{t("today.nothingHint")}</p>}
                </div>
                {data.groups.length === 0 ? (
                  <Card><EmptyState title={t("today.emptyTitle")} hint={t("today.emptyHint")} /></Card>
                ) : (
                  <ul className="space-y-3">{data.groups.map((g) => <li key={g.key}><ThingCard group={g} /></li>)}</ul>
                )}
                {data.total_groups > 0 && (
                  <p className="text-sm">
                    <Link to="/intelligence/things" className="font-medium text-brand-strong hover:underline">
                      {t("today.seeAll", { count: data.total_findings })}
                    </Link>
                  </p>
                )}
              </>
            )}
        </section>
        <aside className="min-w-0 space-y-4">
          {canAsk && <AskBox />}
          <SeeStrip />
          <Slot name={COMMAND_PANELS} props={{ companyId: company?.id }} />
          <SummaryStrip />
        </aside>
      </div>
      <div className="mt-6"><Slot name={TODAY_PANELS} /></div>
    </>
  );
}

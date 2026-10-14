import { useState } from "react";

import { api, ErrorState, PageHeader, SkeletonRows, Tabs, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import AllSchedules from "../components/AllSchedules";
import BriefHistory from "../components/BriefHistory";
import PreviewCard from "../components/PreviewCard";
import ScheduleForm from "../components/ScheduleForm";

export default function BriefsPage() {
  const { t } = useTranslation("command");
  const canManage = useCan("briefs.manage");
  const [tab, setTab] = useState<"mine" | "everyone">("mine");
  const mine = useQuery({ queryKey: ["command", "schedules", "mine"], queryFn: () => unwrap(api.GET("/api/v1/command/schedules/mine")) });

  return (
    <>
      <PageHeader title={t("briefsTitle")} description={t("briefsHint")} back={{ to: "/command", label: t("title") }} />
      {canManage && <Tabs value={tab} onChange={setTab} tabs={[{ id: "mine", label: t("tabMine") }, { id: "everyone", label: t("tabEveryone") }]} />}
      {tab === "everyone" ? <AllSchedules /> : (
        <div className="space-y-6">
          {mine.error ? <ErrorState message={mine.error.message} onRetry={() => void mine.refetch()} />
            : !mine.data ? <SkeletonRows rows={4} cols={2} /> : (
              <div className="grid gap-4 lg:grid-cols-2">
                {/* keyed by what was saved, so the form shows the stored values after a save or removal */}
                {(["daily", "weekly"] as const).map((kind) => {
                  const s = mine.data.find((x) => x.kind === kind);
                  return <ScheduleForm key={`${kind}-${s?.id ?? "none"}-${s?.send_time}-${s?.channel}-${s?.weekday}-${s?.is_active}`} kind={kind} schedule={s} />;
                })}
              </div>
            )}
          <PreviewCard />
          <section>
            <h2 className="mb-2 text-sm font-semibold">{t("history")}</h2>
            <BriefHistory />
          </section>
        </div>
      )}
    </>
  );
}
